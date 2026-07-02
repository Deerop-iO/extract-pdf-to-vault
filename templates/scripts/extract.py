#!/usr/bin/env python3
"""Stage 1: deterministic PDF extraction -> manifest.json (+ staged assets).

Source of truth for the pipeline. Reads a PDF with PyMuPDF + pymupdf4llm,
derives a positional ToC tree, slices page-level markdown per leaf section, and
writes a normalized manifest. Never writes into the vault (that is stage 2).

Usage:
    python extract.py path/to/book.pdf [--config pipeline.config.json]
                                       [--out ../.p2v]
                                       [--fallback pages|headings|toc]
                                       [--ignore-toc]
                                       [--toc-page N]

ToC source precedence (strictly enforced):
1. Embedded ToC present AND --ignore-toc not set → USE IT (toc_source=embedded).
   A --fallback flag passed alongside a present embedded ToC is ignored with a
   notice; pass --ignore-toc to override.
2. Embedded present + --ignore-toc set → drop it, honor --fallback.
3. No embedded ToC → require --fallback.

--fallback toc  reads the document's own printed table-of-contents page(s),
   infers the hierarchy from indentation or numbered prefixes, and auto-detects
   the printed→physical page offset. Requires --ignore-toc when an embedded
   (even degenerate) ToC is present.

When a PDF has no embedded ToC, extraction stops unless a --fallback is given:
``pages`` makes one note per page; ``headings`` reconstructs a flat, page-level
hierarchy from the markdown headings pymupdf4llm already detects (inferred, not
extracted -- labeled as such in the manifest and the vault).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import sys

import fitz  # PyMuPDF
import pymupdf4llm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inspect  # noqa: E402

from lib.slugify import slugify  # noqa: E402
from lib import toc_tree  # noqa: E402
from lib import table_guard  # noqa: E402
from lib import heading_toc  # noqa: E402
from lib.index_layout import reconstruct_index  # noqa: E402
from lib.toc_page import (  # noqa: E402
    toc_from_toc_page,
    embedded_toc_looks_degenerate,
)
from lib.text import (  # noqa: E402
    clean_inline,
    clean_block,
    normalize_body,
    reformat_stat_profiles,
    merge_wrapped_table_rows,
    promote_header_below_separator,
    promote_demoted_label_row,
    collapse_table_headers,
    split_am_traits,
    merge_wrapped_name_rows,
    split_glued_caps_by_gaps,
    apply_heading_space_map,
)

DEFAULTS = {
    "split_depth": 0,  # 0 = no clamp (mirror full ToC depth)
    "pad_width": 2,
    "slug_max_len": 60,
    "tier": "clean",
    "min_text_chars": 200,
    "header": True,  # pass-through to pymupdf4llm.to_markdown
    "footer": True,  # set false to drop running headers / page-number footers
    # Table detection strategy passed to to_markdown. "lines_strict" is the
    # library default (ruled tables); "text" recovers tables from text positions
    # (stat blocks rendered as spaced text); "lines"/None are also valid.
    "table_strategy": "lines_strict",
    "boilerplate_patterns": [],  # regex list, e.g. a DRM ownership watermark
    "strip_page_numbers": True,  # drop standalone page-number lines / table rows
    # Opt-in (clean/enriched tiers): reformat run-on Necromunda fighter/vehicle
    # stat profiles (12-column characteristic rows + 12 values) into markdown
    # tables. Off by default; enable per Necromunda project/source.
    "reformat_stat_blocks": False,
    # Opt-in (clean/enriched tiers): fold wrapped `Traits` continuation rows in
    # Necromunda weapon charts back into the row above. Off by default; enable
    # per Necromunda project/source.
    "merge_wrapped_table_rows": False,
    # Work around a pymupdf4llm quirk that silently drops zero-width ligature
    # glyphs inside TABLE cells ("fighter" -> "fghter", "effect" -> "efect").
    # On by default: it only restores characters MuPDF already extracted, never
    # invents one, and is a no-op on PDFs without the quirk. See
    # _ligature_cell_fix for the mechanism and the version guard.
    "restore_ligatures": True,
    # Opt-in (clean/enriched tiers): further weapon-chart layout cleanups, all
    # protected by the data guard below. Off by default; enable per Necromunda
    # project/source.
    #   promote_header_below_separator -- fix a misplaced header where the real
    #       labels (`Weapon|S|L|...`) landed below the separator, under a near-
    #       empty spanning group row (so Obsidian renders no proper table).
    #   collapse_table_headers  -- fold a two-row (group + sub) header into one.
    #   split_am_traits         -- split a fused `Am Traits` column into two.
    #   merge_wrapped_name_rows -- fold an orphan weapon-name row into the name above.
    "promote_header_below_separator": False,
    "collapse_table_headers": False,
    "split_am_traits": False,
    "merge_wrapped_name_rows": False,
    # Deterministic fabrication guard (on by default; a no-op when no structural
    # rule changes anything). After the structural normalizers run, assert that
    # every table's DATA-row token multiset is unchanged from before they ran;
    # hard-fail the extraction if a token was added, dropped, or altered. See
    # lib/table_guard.py.
    "guard_table_data": True,
    # Opt-in (clean/enriched tiers): repair headings whose display font omits the
    # inter-word space glyph, so the extractor returns a glued run like
    # "RESOLVEHITS". Uses PyMuPDF glyph geometry: a space is reinserted only where
    # the gap between two glyphs on a heading line exceeds
    # heading_space_gap_ratio * font_size -- a clear word boundary. Applied ONLY to
    # markdown heading lines (a glued run in body text is indistinguishable from a
    # real long word without geometry). Off by default; enable per source. See
    # split_glued_caps_by_gaps / apply_heading_space_map in lib/text.py.
    "fix_heading_spaces": False,
    "heading_space_gap_ratio": 0.08,
    # Opt-in (clean/enriched tiers): rebuild a back-of-book alphabetical index
    # section from PDF column geometry instead of pymupdf4llm's flattened text.
    # A printed index is multi-column; a flat reader glues unrelated entries onto
    # one line and scrambles the A-Z order. This re-reads the index section's
    # pages column-by-column, emits one entry per line in true order, strips
    # dotted leaders, and drops the title/footer furniture. Page numbers are left
    # as plain text; build_vault turns them into wikilinks to the covering note.
    # A section is treated as an index when its ToC title matches
    # index_title_pattern. Off by default; enable per source. See
    # lib/index_layout.py.
    # Extract and embed PDF images (figures, diagrams, screenshots) into the
    # manifest. Off by default: most PDFs contain only repeated decorative
    # elements (logos, page-header graphics) that add no signal for an AI-agent
    # workflow. Enable per source (via the "sources" map) for PDFs whose
    # figures carry real content -- architecture diagrams, UI wireframes, etc.
    # Override at runtime with --write-images.
    "write_images": False,
    "reconstruct_index": False,
    "index_title_pattern": r"^\s*index\s*$",
    # --fallback toc: regex (case-insensitive) matching the ToC page heading.
    # Covers common English and European language terms; override per source.
    "toc_title_pattern": (
        r"^\s*(table\s+of\s+contents?|contents?|toc|index"
        r"|inhoud(?:sopgave|stafel)?|inhaltsverzeichnis"
        r"|table\s+des\s+mati[eè]res|[ií]ndice|contenido)\s*$"
    ),
    # --fallback toc: "auto" (default), "indent", or "numbered".
    "toc_hierarchy_mode": "auto",
}

_IMG_MD = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


@contextlib.contextmanager
def _ligature_cell_fix(enabled: bool):
    """Restore zero-width ligature glyphs that pymupdf4llm drops in table cells.

    Many PDFs (e.g. Necromunda) encode ``fi``/``ff``/``fl`` as a ligature whose
    first glyph carries the full advance width and whose trailing component is a
    real but ZERO-WIDTH character (the ``i`` of ``fighter`` arrives as ``U+0069``
    with width ``0.0``). ``page.get_text()`` keeps it, but pymupdf4llm's per-cell
    text builder (``helpers.utils.extract_cells``) only keeps a char whose bbox
    overlaps the cell by >50%, computed by ``almost_in_bbox``; a zero-area glyph
    scores 0% and is dropped -- corrupting table text ("fighter" -> "fghter",
    "effect" -> "efect"). The bug is table-cell-only; body text is unaffected.

    We patch ``almost_in_bbox`` to also keep a degenerate (zero-area) char whose
    origin lies within the cell. That restores a character MuPDF already
    extracted -- it never invents one -- so the fabrication ban is upheld. The
    symbol is imported by value into other modules, so patching the ``utils``
    module attribute only affects the cell-text loop (utils.extract_cells) and
    leaves the line/span clip checks elsewhere untouched.

    Restored on exit so the process stays pure. Version-guarded: if the internal
    symbol is gone on a future pymupdf4llm, we warn and run unpatched rather than
    crash (re-test on dependency bumps).
    """
    if not enabled:
        yield
        return
    try:
        from pymupdf4llm.helpers import utils as _u
    except Exception as exc:  # import surface changed on a future version
        print(
            "WARNING: restore_ligatures: cannot import "
            f"pymupdf4llm.helpers.utils ({exc}); running unpatched. Re-check "
            "after a pymupdf4llm upgrade.",
            file=sys.stderr,
        )
        yield
        return
    orig = getattr(_u, "almost_in_bbox", None)
    if not callable(orig):
        print(
            "WARNING: restore_ligatures: "
            "pymupdf4llm.helpers.utils.almost_in_bbox not found; running "
            "unpatched. Re-check after a pymupdf4llm upgrade.",
            file=sys.stderr,
        )
        yield
        return

    def _patched(bbox, clip, portion=0.8):
        x0, y0, x1, y1 = bbox
        # Degenerate (zero-area) glyph -- e.g. a zero-width ligature component.
        # Keep it iff its origin sits within the cell (1pt tolerance), restoring
        # an already-extracted character instead of silently dropping it.
        if (x1 - x0) <= 0 or (y1 - y0) <= 0:
            return (clip[0] - 1 <= x0 <= clip[2] + 1) and (
                clip[1] - 1 <= y0 <= clip[3] + 1
            )
        return orig(bbox, clip, portion)

    _u.almost_in_bbox = _patched
    try:
        yield
    finally:
        _u.almost_in_bbox = orig


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_config(path: str | None) -> dict:
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    return cfg


# Config keys passed straight through to pymupdf4llm.to_markdown, with the
# library's own default for each. These are the source-level controls over
# running headers / page-number footers and table detection.
_MD_PASSTHROUGH = {"header": True, "footer": True, "table_strategy": "lines_strict"}


def _select_passthrough(
    cfg: dict, supported: set, accepts_var_kw: bool = False
) -> tuple[dict, list]:
    """Return (kwargs_subset, warnings) for the to_markdown pass-through keys.

    Pass a key through if the installed pymupdf4llm names it explicitly OR
    exposes a ``**kwargs`` catch-all (``accepts_var_kw``) -- modern pymupdf4llm
    (1.27+) wraps ``to_markdown`` as ``(*args, **kwargs)``, so a name check alone
    would silently drop every option. If a non-default value was configured on a
    version that can take neither, record a warning rather than crashing.
    ``supported`` is the caller's ``inspect.signature(...).parameters`` set, so
    this helper stays import-pure and unit-testable without PyMuPDF installed.
    """
    kwargs: dict = {}
    warnings: list = []
    for key, default in _MD_PASSTHROUGH.items():
        if key in supported or accepts_var_kw:
            kwargs[key] = cfg[key]
        elif cfg[key] != default:
            warnings.append(
                f"pymupdf4llm.to_markdown has no '{key}' parameter in this "
                f"version; ignoring config {key}={cfg[key]!r}."
            )
    return kwargs, warnings


def _clamp_depth(toc: list, split_depth: int) -> list:
    if not split_depth or split_depth <= 0:
        return toc
    return [entry for entry in toc if int(entry[0]) <= split_depth]


def _rewrite_image_refs(text: str, collected: list) -> str:
    """Replace markdown image paths with ASSET:<basename> sentinels.

    build_vault.py resolves the sentinel to a note-relative path. We only keep
    the basename so the manifest is portable across machines.
    """

    def repl(match: "re.Match[str]") -> str:
        basename = os.path.basename(match.group(1))
        collected.append(basename)
        return f"![]({_ASSET_PREFIX}{basename})"

    return _IMG_MD.sub(repl, text)


_ASSET_PREFIX = "ASSET:"


def _synthetic_toc_from_pages(page_count: int) -> list:
    return [[1, f"Page {i}", i] for i in range(1, page_count + 1)]


def _heading_space_map(
    doc, gap_ratio: float, size_floor: float = 12.0, heading_ratio: float = 1.15
) -> dict:
    """Build a ``{glued: spaced}`` correction map from the PDF's heading geometry.

    Scans every page's ``rawdict`` glyphs, estimates the body font size (median
    line size), and inspects only the large-font *heading band* (lines whose font
    size is >= ``heading_ratio`` x median, above a ``size_floor``). For those
    lines, ``split_glued_caps_by_gaps`` reinserts a space wherever the inter-glyph
    gap marks a word boundary the display font failed to encode. The map is later
    applied solely to markdown heading lines. Deterministic given the PDF + the
    pinned PyMuPDF; a no-op (empty map) on PDFs without the artifact.
    """
    candidates: list = []  # (line_size, [(c, x0, x1), ...])
    sizes: list = []
    for page in doc:
        d = page.get_text("rawdict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                line_size = max((s.get("size", 0.0) for s in spans), default=0.0)
                sizes.append(line_size)
                if line_size < size_floor:
                    continue
                chars = []
                for s in spans:
                    for ch in s.get("chars", []):
                        bbox = ch.get("bbox")
                        if bbox:
                            chars.append((ch.get("c", ""), bbox[0], bbox[2]))
                if chars:
                    candidates.append((line_size, chars))
    if not sizes:
        return {}
    sizes.sort()
    median = sizes[len(sizes) // 2]
    threshold = max(size_floor + 1.0, median * heading_ratio)
    mapping: dict = {}
    for line_size, chars in candidates:
        if line_size >= threshold:
            mapping.update(split_glued_caps_by_gaps(chars, line_size, gap_ratio))
    return mapping


def _page_fragments(doc, page_lo: int, page_hi: int) -> list:
    """Positioned text fragments (one per span) for a 1-based page range.

    Shapes PyMuPDF ``dict`` spans into the input ``lib.index_layout`` expects:
    ``{text, x0, x1, y, size, bold}``. Used to rebuild an index from geometry.
    """
    pages = []
    for pno in range(page_lo, page_hi + 1):
        d = doc[pno - 1].get_text("dict")
        frags = []
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bx = span.get("bbox") or (0, 0, 0, 0)
                    frags.append(
                        {
                            "text": span.get("text", ""),
                            "x0": bx[0],
                            "x1": bx[2],
                            "y": round((bx[1] + bx[3]) / 2, 1),
                            "size": span.get("size", 0.0),
                            "bold": bool(span.get("flags", 0) & 16),
                        }
                    )
        pages.append(frags)
    return pages


def extract(
    pdf_path: str,
    out_dir: str,
    cfg: dict,
    fallback: str | None,
    ignore_toc: bool = False,
    toc_page_num: int | None = None,
    write_images: bool | None = None,
) -> dict:
    doc = fitz.open(pdf_path)
    page_count = doc.page_count
    meta = doc.metadata or {}
    file_name = os.path.basename(pdf_path)
    title = clean_inline(meta.get("title") or "") or os.path.splitext(file_name)[0]
    source_slug = slugify(title, cfg["slug_max_len"])

    # Per-source overrides: an optional "sources" map in the config, keyed by
    # source_slug, is merged over the global config. This lets a single shared
    # config carry e.g. a DRM boilerplate pattern (or a different tier /
    # split_depth) for one PDF without affecting the others. Note: slug_max_len
    # was already used to derive source_slug above, so overriding it per-source
    # has no effect on the slug itself.
    source_overrides = (cfg.get("sources") or {}).get(source_slug)
    if isinstance(source_overrides, dict):
        cfg = {**cfg, **source_overrides}

    raw_toc = doc.get_toc(simple=True) or []
    raw_toc = [[lvl, clean_inline(str(t)), pg] for (lvl, t, pg) in raw_toc]
    toc_source = "embedded"

    # --- ToC source precedence (plan section: "embedded stays preferred") ---
    #
    # Rung 1: Embedded present + --ignore-toc NOT set → use it, always.
    # Rung 2: Embedded present + fallback flag BUT no --ignore-toc → embedded
    #         still wins; flag is silently effective only if --ignore-toc set.
    # Rung 3: --ignore-toc set → drop embedded, honour --fallback.
    # Rung 4: No embedded ToC → require --fallback.
    #
    # The quality heuristic (embedded_toc_looks_degenerate) is a HINT only:
    # it never auto-switches the source.
    if raw_toc and not ignore_toc:
        # Rung 1 / 2: embedded wins.
        if fallback is not None:
            print(
                f"  note: embedded ToC present and used (toc_source=embedded); "
                f"--fallback {fallback!r} ignored. "
                f"Pass --ignore-toc to override.",
                file=sys.stderr,
            )
        if embedded_toc_looks_degenerate(raw_toc):
            print(
                "  warning: the embedded ToC looks degenerate (bare page-number "
                "titles, no hierarchy). It will be used as-is. To reconstruct "
                "from the printed contents page instead, re-run with:\n"
                "    --ignore-toc --fallback toc",
                file=sys.stderr,
            )
        # toc_source stays "embedded"; raw_toc unchanged.
    elif ignore_toc and raw_toc:
        # Rung 3: user explicitly opted out of the embedded ToC.
        raw_toc = []
        toc_source = "ignored"

    if not raw_toc:
        # Rung 3 (after ignore) or Rung 4 (never had one): require --fallback.
        if fallback == "pages":
            raw_toc = _synthetic_toc_from_pages(page_count)
            toc_source = "pages"
        elif fallback == "headings":
            # Heading text only exists after to_markdown() + normalize loop;
            # defer building raw_toc until then. Fail fast only for no-fallback.
            toc_source = "headings"
        elif fallback == "toc":
            # Defer: ToC-page reconstruction also needs per-page markdown.
            toc_source = "toc-page"
        else:
            doc.close()
            raise SystemExit(
                "No embedded table of contents found.\n"
                "Re-run with --fallback toc (parse the document's own contents "
                "page, with real hierarchy), --fallback headings (flat, one note "
                "per heading), or --fallback pages (one note per page)."
            )

    # CLI --write-images overrides the config value (None = not set, use config).
    do_write_images = write_images if write_images is not None else cfg.get("write_images", False)

    # Stage assets outside the vault; build_vault copies them in.
    # Only create the staging dir when images are actually being extracted.
    staging = os.path.join(out_dir, f"{source_slug}.assets")
    if do_write_images:
        os.makedirs(staging, exist_ok=True)
    md_kwargs = dict(
        page_chunks=True,
        write_images=do_write_images,
        image_path=staging if do_write_images else out_dir,
        image_format="png",
    )
    # header/footer/table_strategy are the primary, source-level controls over
    # running headers, page-number footers, and table detection. Pass them
    # through only if the installed pymupdf4llm supports them; warn (don't crash)
    # if a non-default was asked for on a version that lacks the parameter.
    _sig = inspect.signature(pymupdf4llm.to_markdown)
    supported = set(_sig.parameters)
    accepts_var_kw = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in _sig.parameters.values()
    )
    passthrough, md_warnings = _select_passthrough(cfg, supported, accepts_var_kw)
    md_kwargs.update(passthrough)
    with _ligature_cell_fix(cfg["restore_ligatures"]):
        chunks = pymupdf4llm.to_markdown(pdf_path, **md_kwargs)

    # Chunks are returned in document order, one per page -> 1-based index.
    normalize = cfg["tier"] != "structural"
    # Build the heading inter-word-space correction map once from glyph geometry
    # (opt-in). Applied per page to markdown heading lines only.
    heading_space_map: dict = {}
    if normalize and cfg.get("fix_heading_spaces"):
        heading_space_map = _heading_space_map(
            doc, cfg.get("heading_space_gap_ratio", 0.08)
        )
    page_md: dict[int, str] = {}
    page_assets: dict[int, list] = {}
    total_text = 0
    for i, chunk in enumerate(chunks):
        page1 = i + 1
        collected: list = []
        text = _rewrite_image_refs(clean_block(chunk.get("text", "")), collected)
        if normalize:
            text = normalize_body(
                text,
                boilerplate_patterns=cfg["boilerplate_patterns"],
                strip_page_numbers=cfg["strip_page_numbers"],
                page_count=page_count,
            )
            if heading_space_map:
                text = apply_heading_space_map(text, heading_space_map)
            if cfg.get("reformat_stat_blocks"):
                text = reformat_stat_profiles(text)
            # Structural table normalizers run as one guarded group: snapshot the
            # text first, apply the gated rules in order, then assert no data-row
            # token drifted (fabrication guard). reformat_stat_profiles is above
            # the snapshot on purpose -- it builds tables from prose (changing the
            # table count), so it is unguardable by a per-table multiset diff.
            before = text
            if cfg.get("promote_header_below_separator"):
                text = promote_header_below_separator(text)
            text = promote_demoted_label_row(text)
            if cfg.get("collapse_table_headers"):
                text = collapse_table_headers(text)
            if cfg.get("split_am_traits"):
                text = split_am_traits(text)
            if cfg.get("merge_wrapped_table_rows"):
                text = merge_wrapped_table_rows(text)
            if cfg.get("merge_wrapped_name_rows"):
                text = merge_wrapped_name_rows(text)
            if cfg.get("guard_table_data") and text != before:
                drift = table_guard.data_drift(before, text)
                if drift:
                    doc.close()
                    raise SystemExit(
                        f"table_guard: structural table normalization changed "
                        f"DATA on page {page1} (fabrication guard tripped). The "
                        f"rules must only move layout, never data:\n  "
                        + "\n  ".join(drift)
                    )
        page_md[page1] = text
        page_assets[page1] = collected
        total_text += len(chunk.get("text", ""))

    if total_text < cfg["min_text_chars"] and toc_source != "pages":
        doc.close()
        raise SystemExit(
            f"Extracted only {total_text} characters of text; this PDF looks "
            "scanned / image-only. OCR is opt-in and not enabled. Enable it in "
            "pipeline.config.json or run an OCR pass first."
        )

    # Deferred fallback: build raw_toc now that per-page markdown exists.
    warnings_extra: list = []
    if toc_source == "headings":
        page_texts = [page_md.get(p, "") for p in range(1, page_count + 1)]
        raw_toc = heading_toc.toc_from_headings(page_texts)
        if not raw_toc:
            doc.close()
            raise SystemExit(
                "--fallback headings found no usable heading text in this PDF; "
                "re-run with --fallback pages instead."
            )
        warnings_extra.append(
            f"No embedded ToC; hierarchy reconstructed from {len(raw_toc)} "
            f"detected heading(s) (inferred, not extracted -- verify structure "
            f"before relying on it)."
        )

    elif toc_source == "toc-page":
        # Locate the ToC page run by matching toc_title_pattern against page
        # headings, then optionally extend across contiguous dot-leader pages.
        page_texts = [page_md.get(p, "") for p in range(1, page_count + 1)]
        toc_title_re = re.compile(
            cfg.get(
                "toc_title_pattern",
                r"^\s*(table\s+of\s+contents?|contents?|toc|index"
                r"|inhoud(?:sopgave|stafel)?|inhaltsverzeichnis"
                r"|table\s+des\s+mati[eè]res|[ií]ndice|contenido)\s*$",
            ),
            re.IGNORECASE,
        )
        # If --toc-page N was given, pin; otherwise auto-detect.
        if toc_page_num is not None:
            toc_start = max(1, min(toc_page_num, page_count))
        else:
            toc_start = None
            for pno, md in enumerate(page_texts, start=1):
                for line in (md or "").splitlines():
                    stripped = line.strip()
                    # Match against bare text OR markdown heading text.
                    m_h = re.match(r"^#{1,6}\s+(.+)$", stripped)
                    candidate = m_h.group(1).strip() if m_h else stripped
                    if candidate and toc_title_re.match(candidate):
                        toc_start = pno
                        break
                if toc_start:
                    break

        if toc_start is None:
            doc.close()
            raise SystemExit(
                "--fallback toc: could not find a table of contents page "
                f"matching toc_title_pattern {cfg.get('toc_title_pattern')!r}.\n"
                "Re-run with --toc-page N to pin the page number explicitly, "
                "or use --fallback headings / --fallback pages."
            )

        # Gather the ToC page run: start page + any immediately following pages
        # that still look like ToC pages (have dot-leader rows).
        _DOT_LEADER = re.compile(r"[.\u00b7\u2026]{4,}")
        toc_pages_range = [toc_start]
        for pno in range(toc_start + 1, min(toc_start + 20, page_count + 1)):
            md = page_md.get(pno, "")
            if _DOT_LEADER.search(md or ""):
                toc_pages_range.append(pno)
            else:
                break

        toc_frags = _page_fragments(doc, toc_pages_range[0], toc_pages_range[-1])
        raw_toc, toc_warnings = toc_from_toc_page(
            toc_frags,
            page_texts,
            hierarchy_mode=cfg.get("toc_hierarchy_mode", "auto"),
        )
        warnings_extra.extend(toc_warnings)

        if not raw_toc:
            doc.close()
            raise SystemExit(
                "--fallback toc: ToC-page reconstruction found no usable "
                f"structure on page(s) {toc_pages_range}.\n"
                + (("\n".join(toc_warnings) + "\n") if toc_warnings else "")
                + "Re-run with --fallback headings or --fallback pages."
            )
        warnings_extra.append(
            f"Hierarchy reconstructed from printed ToC page(s) "
            f"{toc_pages_range} ({len(raw_toc)} entries, "
            f"toc_source=toc-page -- inferred, not extracted; verify structure)."
        )

    toc = _clamp_depth(raw_toc, cfg["split_depth"])
    sections = toc_tree.build_sections(
        toc, page_count, pad_width=cfg["pad_width"], slug_max_len=cfg["slug_max_len"]
    )

    warnings: list = list(md_warnings) + warnings_extra
    seen_pages: dict[int, str] = {}
    for s in sections:
        # Leaves own their full page range; a branch owns only the "preamble"
        # pages before its first child (chapter intro/content above its one
        # bookmarked subsection) -- without this, that content would be dropped.
        if s["is_leaf"]:
            page_lo, page_hi = s["start_page"], s["end_page"]
        else:
            preamble = toc_tree.branch_preamble_range(s, sections)
            if preamble is None:
                continue
            page_lo, page_hi = preamble

        body_parts = []
        assets = []
        for p in range(page_lo, page_hi + 1):
            body_parts.append(page_md.get(p, ""))
            for name in page_assets.get(p, []):
                assets.append({"ref": name, "page": p, "kind": "image"})
            if p in seen_pages and seen_pages[p] != s["toc_number"]:
                warnings.append(
                    f"Page {p} is shared by sections {seen_pages[p]} and "
                    f"{s['toc_number']}; boundary is page-level."
                )
            seen_pages.setdefault(p, s["toc_number"])
        s["markdown"] = "\n\n".join(part for part in body_parts if part).strip()
        s["assets"] = assets

    # Optional: rebuild any index section from column geometry. A section is an
    # index when its ToC title matches the configured pattern; reconstruction
    # replaces the flattened markdown and tags the section ("kind": "index") so
    # build_vault links the page numbers. On no match or no recognisable
    # multi-column structure it keeps the normal extraction AND records a warning
    # (an enabled-but-inert flag is surfaced, never silently swallowed).
    if normalize and cfg.get("reconstruct_index"):
        index_re = re.compile(cfg.get("index_title_pattern", r"^\s*index\s*$"), re.I)
        matched = 0
        for s in sections:
            # ToC titles can carry control-char padding (e.g. NULs); strip before matching.
            clean_title = re.sub(r"[\x00-\x1f]+", "", s.get("title", "")).strip()
            if not s.get("is_leaf") or not index_re.match(clean_title):
                continue
            matched += 1
            frags = _page_fragments(doc, s["start_page"], s["end_page"])
            md = reconstruct_index(frags, title=clean_title)
            if md:
                s["markdown"] = md
                s["kind"] = "index"
                s["assets"] = []
            else:
                warnings.append(
                    f"reconstruct_index: section {s['toc_number']} ('{clean_title}', "
                    f"pages {s['start_page']}-{s['end_page']}) has no recognisable "
                    "multi-column index layout; kept the normal extraction."
                )
        if not matched:
            warnings.append(
                "reconstruct_index is enabled but no leaf section title matched "
                f"index_title_pattern {cfg.get('index_title_pattern')!r}; nothing reconstructed."
            )

    manifest = {
        "schema_version": 1,
        "source": {
            "file_path": os.path.abspath(pdf_path),
            "file_name": file_name,
            "title": title,
            "author": (meta.get("author") or "").strip(),
            "source_slug": source_slug,
            "page_count": page_count,
            "sha256": _sha256(pdf_path),
            "extracted_at": _dt.date.today().isoformat(),
            "assets_staging_dir": os.path.abspath(staging),
        },
        "tooling": {
            "pymupdf": fitz.VersionBind,
            "pymupdf4llm": getattr(pymupdf4llm, "__version__", "unknown"),
        },
        "config": {
            "split_depth": cfg["split_depth"],
            "pad_width": cfg["pad_width"],
            "slug_max_len": cfg["slug_max_len"],
            "tier": cfg["tier"],
            "header": cfg["header"],
            "footer": cfg["footer"],
            "table_strategy": cfg["table_strategy"],
            "strip_page_numbers": cfg["strip_page_numbers"],
            "boilerplate_patterns": cfg["boilerplate_patterns"],
            "reformat_stat_blocks": cfg["reformat_stat_blocks"],
            "merge_wrapped_table_rows": cfg["merge_wrapped_table_rows"],
            "restore_ligatures": cfg["restore_ligatures"],
            "promote_header_below_separator": cfg["promote_header_below_separator"],
            "collapse_table_headers": cfg["collapse_table_headers"],
            "split_am_traits": cfg["split_am_traits"],
            "merge_wrapped_name_rows": cfg["merge_wrapped_name_rows"],
            "guard_table_data": cfg["guard_table_data"],
            "fix_heading_spaces": cfg["fix_heading_spaces"],
            "heading_space_gap_ratio": cfg["heading_space_gap_ratio"],
            "reconstruct_index": cfg["reconstruct_index"],
            "index_title_pattern": cfg["index_title_pattern"],
            "toc_title_pattern": cfg.get("toc_title_pattern", ""),
            "toc_hierarchy_mode": cfg.get("toc_hierarchy_mode", "auto"),
            "write_images": do_write_images,
        },
        "toc_present": bool(raw_toc),
        "toc_source": toc_source,
        "sections": sections,
        "warnings": sorted(set(warnings)),
    }
    doc.close()
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a PDF to a p2v manifest.")
    parser.add_argument("pdf", help="Path to the source PDF")
    parser.add_argument("--config", default="pipeline.config.json")
    parser.add_argument("--out", default="../.p2v", help="Manifest/staging output dir")
    parser.add_argument("--fallback", choices=["pages", "headings", "toc"], default=None)
    parser.add_argument(
        "--ignore-toc",
        action="store_true",
        default=False,
        help=(
            "Ignore the embedded ToC (even if present), then apply --fallback. "
            "Required when the embedded ToC is degenerate (e.g. bare page numbers)."
        ),
    )
    parser.add_argument(
        "--toc-page",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Pin the (1-based) starting page of the printed ToC for "
            "--fallback toc; skips auto-detection via toc_title_pattern."
        ),
    )
    parser.add_argument(
        "--write-images",
        action="store_true",
        default=False,
        help=(
            "Extract and embed PDF images (figures, diagrams) into the manifest. "
            "Overrides write_images in pipeline.config.json for this run. "
            "Off by default; enable for PDFs whose figures carry real content."
        ),
    )
    args = parser.parse_args()

    cfg = _load_config(args.config)
    os.makedirs(args.out, exist_ok=True)
    manifest = extract(
        args.pdf,
        args.out,
        cfg,
        args.fallback,
        ignore_toc=args.ignore_toc,
        toc_page_num=args.toc_page,
        write_images=args.write_images if args.write_images else None,
    )

    slug = manifest["source"]["source_slug"]
    out_path = os.path.join(args.out, f"{slug}.manifest.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False, sort_keys=False)

    leaves = sum(1 for s in manifest["sections"] if s["is_leaf"])
    print(f"Wrote {out_path}")
    print(
        f"  title={manifest['source']['title']!r} pages={manifest['source']['page_count']} "
        f"sections={len(manifest['sections'])} leaves={leaves} "
        f"toc_source={manifest['toc_source']}"
    )
    for w in manifest["warnings"]:
        print(f"  warning: {w}")


if __name__ == "__main__":
    main()
