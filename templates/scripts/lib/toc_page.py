"""Reconstruct a table of contents hierarchy from the PDF's own ToC page(s).

When a PDF has no usable embedded outline (doc.get_toc() is empty or degenerate),
this module reads the printed table of contents page(s) — the page a reader would
turn to at the start of the book — and recovers a proper [[level, title, page]]
list that matches what get_toc() would have returned for a well-authored PDF.

Two layout modes are supported and auto-detected:

  indent   -- hierarchy is encoded in x0 indentation bands (common in design
              documents, corporate reports). Each distinct x0 band maps to a
              level; the annex_project_pack_bible PDF is this style:
                x0≈53 (bold)  → L1  (Foundation Platform, Internal Platform…)
                x0≈64         → L2  (Self-Serve Silver, K10 Simple…)
                x0≈75         → L3  (Pack Detail Page, Dashboard & Navigation…)
                x0≈83         → L4  (Project & Pack Store, Add System…)

  numbered -- hierarchy is encoded in outline prefixes: "1", "1.1", "1.1.2",
              "A.1", etc.  Level = number of dot-separated segments.

  auto     -- (default) pick numbered when ≥ 60 % of rows with page numbers
              start with a numeric/letter outline prefix, else indent.

Each row on a ToC page has the shape:

    <optional-indent>  Title text .... page-number

This module strips dot leaders, peels the trailing page number, classifies each
row's depth, then returns ``[[level, title, physical_page], ...]``.

Printed page numbers often differ from physical (PDF) page indices when a
document has unnumbered front matter. ``detect_page_offset`` auto-detects the
offset by matching a sample of ToC titles against headings found in the already-
extracted per-page markdown, taking the modal ``physical - printed`` value.

Pure (no PyMuPDF): the caller supplies fragment dicts and markdown strings;
the module is fully unit-testable with synthetic data.

Input fragments: ``{"text": str, "x0": float, "x1": float, "y": float,
"size": float, "bold": bool}``.  Same shape as ``lib.index_layout``.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import List, Optional, Tuple

# A run that is only dotted-leader characters.
_DOT_RUN = re.compile(r"[.\u00b7\u2026]{2,}")
# Trailing page number: optional bold markers, one or more digits, end.
_TRAILING_PAGE = re.compile(r"\s+(\*{0,2})(\d+)\1\s*$")
# A title that is *only* digits (bare page-number entry in a degenerate ToC).
_BARE_NUMBER = re.compile(r"^\d+$")
# ATX heading line in markdown.
_MD_HEADING = re.compile(r"^#{1,6}\s+(.+)$")
# Fenced code block delimiter.
_FENCE = re.compile(r"^\s*(```|~~~)")

# Leading page + pipe separator: "7 | Chapter 1" or "122 |"  (page before title).
_LEADING_PAGE_PIPE = re.compile(r"^(\d+)\s*\|\s*(.*?)$")
# Leading page without pipe: "1 Introduction"  (digit then non-digit title).
_LEADING_PAGE_NO_PIPE = re.compile(r"^(\d+)\s+([^\d|].+)$")
# A label like "Chapter 1" / "Chapter 12" that is a structural label, not a title.
_CHAPTER_LABEL = re.compile(r"^Chapter\s+\d+$", re.IGNORECASE)

# Numbered outline prefix: "1", "1.1", "A.1", "1.1.2", "B.2.3" etc.
_NUMBERED_PREFIX = re.compile(
    r"^([A-Z0-9]+(?:\.[A-Z0-9]+)*)(?:\s|$)", re.IGNORECASE
)

# Fraction of rows that must carry an outline prefix for numbered-mode to win.
_NUMBERED_THRESHOLD = 0.6


# ---------------------------------------------------------------------------
# Low-level row helpers
# ---------------------------------------------------------------------------


def _group_rows(frags: List[dict], y_tol: float = 4.0) -> List[List[dict]]:
    """Cluster fragments into rows by baseline y; sort each row left-to-right."""
    rows: List[List[dict]] = []
    for f in sorted(frags, key=lambda f: (f["y"], f["x0"])):
        if rows and abs(f["y"] - rows[-1][0]["y"]) <= y_tol:
            rows[-1].append(f)
        else:
            rows.append([f])
    for r in rows:
        r.sort(key=lambda f: f["x0"])
    return rows


def _strip_leaders(text: str) -> str:
    text = _DOT_RUN.sub(" ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    return text.strip()


def _normalize_title(t: str) -> str:
    """Lower-case, strip combining accents, collapse whitespace — for heading matching."""
    nfkd = unicodedata.normalize("NFKD", t.lower())
    ascii_ = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", ascii_).strip()


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------


def _parse_rows(
    pages_frags: List[List[dict]],
) -> List[Tuple[str, Optional[int], float]]:
    """Return ``[(title, printed_page_or_None, min_x0), ...]`` for every ToC row.

    Rows without a trailing page number are kept with ``printed_page=None``
    (they may be section-group headings without a target page); they are skipped
    when building the final ToC list but their x0 contributes to the indent
    band calibration.

    Three page-number patterns are recognised (in order of priority):

    1. ``leading-page | title``  — ``"7 | Chapter 1"`` or ``"122 |"``;
       when the title part is empty or a bare chapter label (``"Chapter N"``),
       the *next* row is consumed as the real title.
    2. ``leading-page title``    — ``"1 Introduction"`` (digit then non-digit
       title on the same row, pipe on a separate row due to font-size y-shift).
    3. ``title ... page``        — classic dot-leader trailing-integer style.
    """
    results: List[Tuple[str, Optional[int], float]] = []
    for frags in pages_frags:
        frags = [f for f in frags if f.get("text", "").strip()]
        if not frags:
            continue
        rows = _group_rows(frags)
        i = 0
        while i < len(rows):
            row = rows[i]
            raw = " ".join(f.get("text", "") for f in row if f.get("text", "").strip())
            cleaned = _strip_leaders(raw)
            if not cleaned:
                i += 1
                continue

            x0 = row[0]["x0"] if row else 0.0

            # --- Pattern 1: leading page + pipe ---
            m_pipe = _LEADING_PAGE_PIPE.match(cleaned)
            if m_pipe:
                page = int(m_pipe.group(1))
                title_hint = m_pipe.group(2).strip()
                if not title_hint or _CHAPTER_LABEL.match(title_hint):
                    # Real title is on the next row (two-row layout).
                    if i + 1 < len(rows):
                        next_raw = " ".join(
                            f.get("text", "") for f in rows[i + 1]
                            if f.get("text", "").strip()
                        )
                        next_cleaned = _strip_leaders(next_raw)
                        if (
                            next_cleaned
                            and not _LEADING_PAGE_PIPE.match(next_cleaned)
                            and not _LEADING_PAGE_NO_PIPE.match(next_cleaned)
                            and not _TRAILING_PAGE.search(next_cleaned)
                        ):
                            title = next_cleaned
                            # Use the title row's x0 for level detection; the
                            # separator row's x0 reflects digit font-size, not depth.
                            title_x0 = rows[i + 1][0]["x0"] if rows[i + 1] else x0
                            i += 1  # consume the lookahead row
                        else:
                            title = title_hint or cleaned
                            title_x0 = x0
                    else:
                        title = title_hint or cleaned
                        title_x0 = x0
                else:
                    title = title_hint
                    # Title fragment is to the right of the pipe; use the x0 of
                    # the rightmost fragment in the row as the indent indicator.
                    title_x0 = max(f["x0"] for f in row) if row else x0
                if title:
                    results.append((title, page, title_x0))
                i += 1
                continue

            # --- Pattern 2: leading page, no pipe (e.g. "1 Introduction") ---
            m_nopipe = _LEADING_PAGE_NO_PIPE.match(cleaned)
            if m_nopipe:
                page = int(m_nopipe.group(1))
                title = m_nopipe.group(2).strip()
                # Title fragment is to the right of the digit; use the x0 of
                # the rightmost fragment in the row as the indent indicator.
                title_x0 = max(f["x0"] for f in row) if row else x0
                if _CHAPTER_LABEL.match(title):
                    # Look ahead for the real title on the next row.
                    if i + 1 < len(rows):
                        next_raw = " ".join(
                            f.get("text", "") for f in rows[i + 1]
                            if f.get("text", "").strip()
                        )
                        next_cleaned = _strip_leaders(next_raw)
                        if (
                            next_cleaned
                            and not _LEADING_PAGE_PIPE.match(next_cleaned)
                            and not _LEADING_PAGE_NO_PIPE.match(next_cleaned)
                            and not _TRAILING_PAGE.search(next_cleaned)
                        ):
                            title = next_cleaned
                            title_x0 = rows[i + 1][0]["x0"] if rows[i + 1] else title_x0
                            i += 1
                if title:
                    results.append((title, page, title_x0))
                i += 1
                continue

            # --- Pattern 3: classic trailing page number ---
            m_trail = _TRAILING_PAGE.search(cleaned)
            if m_trail:
                title = cleaned[: m_trail.start()].strip()
                page = int(m_trail.group(2))
                # Skip structural label rows (e.g. "Chapter 1") where the
                # trailing digit is the chapter number, not a ToC page number.
                if _CHAPTER_LABEL.match(cleaned):
                    title = cleaned
                    page = None
            else:
                title = cleaned
                page = None
            if title:
                results.append((title, page, x0))
            i += 1
    return results


# ---------------------------------------------------------------------------
# Indentation-based level inference
# ---------------------------------------------------------------------------


def _x0_bands(x0_values: List[float], tol: float = 2.5) -> List[float]:
    """Cluster x0 values into distinct indent levels; return sorted representatives."""
    if not x0_values:
        return []
    sorted_vals = sorted(set(x0_values))
    bands: List[float] = [sorted_vals[0]]
    for v in sorted_vals[1:]:
        if v - bands[-1] > tol:
            bands.append(v)
    return bands  # shallow → deep


def _level_from_indent(x0: float, bands: List[float], tol: float = 2.5) -> int:
    for i, b in enumerate(bands):
        if abs(x0 - b) <= tol:
            return i + 1
    # Nearest band fallback.
    dists = [(abs(x0 - b), i) for i, b in enumerate(bands)]
    return min(dists)[1] + 1


# ---------------------------------------------------------------------------
# Numbered-prefix level inference
# ---------------------------------------------------------------------------


def _level_from_prefix(title: str) -> Tuple[Optional[int], str]:
    """Return ``(level, cleaned_title)`` when *title* starts with an outline
    prefix (e.g. ``"1.2 Methods"`` → ``(2, "Methods")``), else ``(None, title)``."""
    m = _NUMBERED_PREFIX.match(title.strip())
    if not m:
        return None, title
    prefix = m.group(1)
    # Must contain a dot OR be a bare digit; bare uppercase letters (e.g. "A")
    # alone are not treated as an outline prefix (could be a chapter letter).
    if "." not in prefix and not prefix.isdigit():
        return None, title
    level = len(prefix.split("."))
    rest = title[m.end():].strip()
    return level, rest if rest else title


def _prefix_coverage(rows: List[Tuple[str, Optional[int], float]]) -> float:
    """Fraction of rows with a page number whose title has a numbered prefix."""
    with_page = [r for r in rows if r[1] is not None]
    if not with_page:
        return 0.0
    hits = sum(1 for r in with_page if _level_from_prefix(r[0])[0] is not None)
    return hits / len(with_page)


# ---------------------------------------------------------------------------
# Page-offset auto-detection
# ---------------------------------------------------------------------------


def _headings_from_md(page_md: List[str]) -> dict:
    """Return ``{physical_page: [normalized_heading, ...]}`` from per-page markdown."""
    result: dict = {}
    for i, text in enumerate(page_md):
        page = i + 1
        headings = []
        in_fence = False
        for line in (text or "").split("\n"):
            if _FENCE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m_h = _MD_HEADING.match(line.strip())
            if m_h:
                headings.append(_normalize_title(m_h.group(1)))
        if headings:
            result[page] = headings
    return result


def detect_page_offset(
    rows: List[Tuple[str, Optional[int], float]],
    page_md: List[str],
    sample_size: int = 20,
) -> Tuple[int, List[str]]:
    """Auto-detect ``offset`` such that ``physical_page = printed_page + offset``.

    Samples ToC rows, finds physical pages whose headings contain the row title
    (normalized substring match), collects ``physical - printed`` votes, and
    returns the modal offset.  Returns ``(0, [warning])`` when no matches found.
    """
    heading_map = _headings_from_md(page_md)
    votes: List[int] = []
    warnings: List[str] = []

    rows_with_page = [r for r in rows if r[1] is not None]
    step = max(1, len(rows_with_page) // sample_size)
    sample = rows_with_page[::step][:sample_size]

    for title, printed, _ in sample:
        norm = _normalize_title(title)
        for phys, headings in heading_map.items():
            if any(norm in h or h in norm for h in headings):
                votes.append(phys - printed)
                break

    if not votes:
        warnings.append(
            "toc-page: could not match ToC titles to page headings; "
            "assuming offset 0 (printed == physical). "
            "Use --toc-page to pin the ToC start page if this is wrong."
        )
        return 0, warnings

    c = Counter(votes)
    modal_offset, modal_count = c.most_common(1)[0]
    if modal_count < max(2, len(votes) // 2):
        warnings.append(
            f"toc-page: page offset inconsistent across {len(votes)} sample(s) "
            f"(modal={modal_offset}, count={modal_count}/{len(votes)}); "
            f"using modal offset {modal_offset}."
        )
    return modal_offset, warnings


# ---------------------------------------------------------------------------
# Degeneracy hint for embedded ToC
# ---------------------------------------------------------------------------


def embedded_toc_looks_degenerate(raw_toc: List[list]) -> bool:
    """Return True when the embedded ToC looks unusable as a content hierarchy.

    Triggers when ≥ half the titles are bare page numbers, OR every entry is
    level 1 with a purely numeric title.  This is the pattern produced by PDF
    authoring tools that add bookmarks named after page numbers instead of
    section titles.

    This helper is a hint only: it never changes which ToC source is used.
    ``extract.py`` emits a console suggestion when it fires.
    """
    if not raw_toc:
        return False
    titles = [str(entry[1]).strip() for entry in raw_toc]
    levels = [int(entry[0]) for entry in raw_toc]
    bare_count = sum(1 for t in titles if _BARE_NUMBER.match(t))
    if bare_count >= len(titles) / 2:
        return True
    if all(lvl == 1 for lvl in levels) and all(t.isdigit() for t in titles):
        return True
    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def toc_from_toc_page(
    pages_frags: List[List[dict]],
    page_md: List[str],
    *,
    hierarchy_mode: str = "auto",
) -> Tuple[List[list], List[str]]:
    """Reconstruct a ``[[level, title, physical_page], ...]`` ToC from the
    document's printed table-of-contents page(s).

    Args:
        pages_frags:    One list of fragment dicts per ToC page, in order.
                        Fragments: ``{"text", "x0", "x1", "y", "size", "bold"}``.
        page_md:        Full per-page markdown for the whole document
                        (``page_md[i]`` = physical page ``i+1``), used only for
                        page-offset detection.
        hierarchy_mode: ``"auto"`` (default), ``"indent"``, or ``"numbered"``.

    Returns:
        ``(toc_list, warnings)`` where ``toc_list`` is empty (not a flattened
        fallback) when no usable structure was found.  The caller must stop and
        report the error rather than proceeding with an empty structure.
    """
    rows = _parse_rows(pages_frags)
    rows_with_page = [(t, p, x0) for t, p, x0 in rows if p is not None]

    if not rows_with_page:
        return [], [
            "toc-page: no rows with a page number were found on the ToC page(s); "
            "re-run with --fallback headings or --fallback pages."
        ]

    # Choose hierarchy mode.
    if hierarchy_mode == "auto":
        use_numbered = _prefix_coverage(rows) >= _NUMBERED_THRESHOLD
    elif hierarchy_mode == "numbered":
        use_numbered = True
    else:
        use_numbered = False  # "indent"

    # Build (level, title, printed_page) triples.
    if use_numbered:
        triples: List[Tuple[int, str, int]] = []
        for title, page, _ in rows_with_page:
            lvl, clean = _level_from_prefix(title)
            if lvl is None:
                lvl, clean = 1, title
            triples.append((lvl, clean, page))
    else:
        # Use only rows that carry a page number for x0 calibration; no-page
        # rows can be layout artifacts (ToC page title, visual separators) that
        # would inject spurious indent bands and inflate levels.
        x0_all = [x0 for _, p, x0 in rows if p is not None]
        bands = _x0_bands(x0_all)
        triples = []
        for title, page, x0 in rows_with_page:
            lvl = _level_from_indent(x0, bands)
            triples.append((lvl, title, page))

    # Auto-detect printed → physical offset.
    offset, offset_warnings = detect_page_offset(rows, page_md)

    # Apply offset, clamp to [1, page_count].
    page_count = max(len(page_md), 1)
    result: List[list] = []
    for lvl, title, printed in triples:
        physical = max(1, min(printed + offset, page_count))
        result.append([lvl, title, physical])

    return result, offset_warnings
