"""Text sanitization for content coming out of PDFs.

PDF ToC bookmark titles and extracted text can carry control characters --
most notably NUL bytes (`\\x00`) from UTF-16-encoded bookmarks. Left in place
they break YAML frontmatter, corrupt wikilink aliases, and make notes look like
binary files. Clean at the boundary so the manifest and the vault stay text.

`normalize_body` is a second, optional pass (clean/enriched tiers only) that
strips recurring PDF *artifacts* the extractor leaks into the body: configured
boilerplate (e.g. a DRM/ownership watermark) and standalone page-number lines.
It is deliberately conservative -- it removes only the boilerplate it matches,
the furniture residue left where it excised that boilerplate, and standalone
page-number lines. It NEVER deletes a table row on a numeric/empty heuristic:
point-total subtotals (``|||||504|``) and blank character-sheet form rows look
identical to "junk", so such rows are kept and any genuinely malformed table is
left for ``verify_vault.py`` to flag, never silently rewritten.

`collapse_spaced_caps` normalizes spaced-letter PDF font artifacts (e.g.
``C H A P T E R`` -> ``CHAPTER``). Inside `normalize_body` it is applied ONLY
to markdown heading lines, because it cannot distinguish a spaced-out title
from a single-letter stat-table column run (Necromunda's ``M WS BS S T W I A``)
-- collapsing the latter would corrupt game data. It is also a public helper so
`extract.py` can apply it to values known to be titles (e.g. ToC bookmark
titles on PDFs with decorative display fonts).
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Pattern

# Control characters except tab (\x09) and newline (\x0a).
_CTRL_KEEP_WS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# All control characters (for inline values like titles, which have no newlines).
_CTRL_ALL = re.compile(r"[\x00-\x1f\x7f]")

# A line that is nothing but a (optionally **bold**) integer -- i.e. a standalone
# page number. The numeric value is captured so callers can bound it by page count.
_PAGE_NUM = re.compile(r"^\*{0,2}(\d{1,4})\*{0,2}$")
# Collapse 3+ consecutive newlines (left behind by removed lines) down to 2.
_BLANK_RUN = re.compile(r"\n{3,}")
# HTML line breaks pymupdf4llm emits inside a cell/paragraph.
_BR = re.compile(r"<br\s*/?>", re.I)
# Interior runs of 2+ spaces (left by mid-line excision); leading indent is kept.
_INNER_SPACES = re.compile(r"(?<=\S) {2,}(?=\S)")
# Spaced-out uppercase letters: PDF font artifact where each glyph is kerned
# individually -- e.g. "C H A P T E R" instead of "CHAPTER". Requires >=3 letters
# (2 repetitions of "X ") to avoid collapsing two-letter abbreviations like "I O".
_SPACED_CAPS = re.compile(r"(?<![A-Za-z])([A-Z] ){2,}[A-Z](?![A-Za-z])")
# A markdown ATX heading line: capture the `#`-prefix and the heading content.
_HEADING_LINE = re.compile(r"^(#{1,6}\s+)(.*)$")
# Markdown emphasis / punctuation that can wrap a heading token; stripped only to
# find the bare word for a geometry-map lookup (the wrappers are preserved).
_TOKEN_WRAP = "*_`#:.,;!?()[]\u2019'\""


def collapse_spaced_caps(s: str) -> str:
    """Collapse PDF spaced-letter font artifacts: 'C H A P T E R' -> 'CHAPTER'.

    Matches runs of >=3 uppercase letters where each is separated by a single
    space (2+ repetitions of the '[A-Z] ' unit). The 2-rep minimum avoids
    collapsing two-letter abbreviations like 'I O'.

    Also collapses any interior double-spaces left between collapsed words
    (e.g. 'CHAPTER  FOUR' -> 'CHAPTER FOUR') via ``_INNER_SPACES``.

    KNOWN LIMITATION -- this only collapses fully-spaced runs. Residual forms
    where kerning fused some glyphs ('C H A P T E R  T WO' leaves 'T WO';
    'PHILTRE OF F URY' splits one letter) are NOT auto-corrected: a rule
    aggressive enough to join 'F URY' -> 'FURY' would also corrupt legitimate
    text like '(A OR B)' -> '(AORB)' or 'A NEW ERA' -> 'ANEW ERA'. Such forms
    are structurally indistinguishable from real text, so they are left for
    human review rather than silently rewritten.

    CAUTION -- this is purely structural and CANNOT tell a spaced-out *word*
    from a row of single-letter *column abbreviations*. Wargame stat tables
    (e.g. Necromunda's ``M WS BS S T W I A Ld Cl Wil Int``) contain a single-
    letter sub-run (``S T W I A``) that matches and would be mangled into
    ``STWIA``. The only reliable signal that a run is a title and not data is
    *context*, so the body caller (``normalize_body``) applies this ONLY to
    markdown heading lines, never to table/stat rows. Use it directly only on
    values that are known to be titles (e.g. a ToC bookmark title).
    """
    if not s:
        return ""
    collapsed = _SPACED_CAPS.sub(lambda m: m.group(0).replace(" ", ""), s)
    return _INNER_SPACES.sub(" ", collapsed)


def split_glued_caps_by_gaps(chars, size, gap_ratio: float = 0.08) -> dict:
    """Build a ``{glued_token: spaced_token}`` map from one rendered line's glyph
    geometry.

    ``chars`` is an ordered list of ``(text, x0, x1)`` tuples for a single line
    (e.g. PyMuPDF ``rawdict`` char bboxes); ``size`` is the line's font size.

    Many display fonts omit the space *glyph* between words yet keep the visual
    gap, so the extractor returns a glued run like ``RESOLVEHITS``. MuPDF only
    auto-inserts a space when the gap is large relative to the font, so tightly
    set large headings slip under that threshold. Here we reinsert a space
    wherever the gap between two glyphs *within one whitespace-delimited token*
    exceeds ``gap_ratio * size`` -- a clear word boundary. This is geometry only:
    it never adds, drops, or alters a glyph, it only inserts ASCII spaces, so the
    fabrication ban is upheld.

    Returns a dict for the tokens that gained at least one space
    (e.g. ``{"RESOLVEHITS": "RESOLVE HITS"}``); unchanged tokens are omitted.
    """
    if not chars or not size:
        return {}
    threshold = gap_ratio * size
    mapping: dict = {}

    def _flush(tok: list) -> None:
        if len(tok) < 2:
            return
        glued = "".join(c for (c, _x0, _x1) in tok)
        parts = [tok[0][0]]
        for i in range(1, len(tok)):
            if (tok[i][1] - tok[i - 1][2]) > threshold:
                parts.append(" ")
            parts.append(tok[i][0])
        spaced = "".join(parts)
        if spaced != glued and " " in spaced:
            mapping[glued] = spaced

    token: list = []
    for (c, x0, x1) in chars:
        if c.isspace():
            _flush(token)
            token = []
        else:
            token.append((c, x0, x1))
    _flush(token)
    return mapping


def apply_heading_space_map(text: str, mapping: dict) -> str:
    """Reinsert word spaces in markdown heading lines using a geometry map.

    For every ATX heading line (``# ``..``###### ``), each whitespace-delimited
    token is looked up in ``mapping`` (after stripping wrapping emphasis /
    punctuation) and, on a hit, replaced by its spaced form -- the markdown
    wrappers (``**``, etc.) are preserved. Only heading lines are touched; body
    text is left untouched because a glued run there cannot be told apart from a
    legitimate long word without the PDF geometry.
    """
    if not mapping:
        return text
    out: List[str] = []
    for line in text.split("\n"):
        m = _HEADING_LINE.match(line)
        if not m:
            out.append(line)
            continue
        prefix, content = m.group(1), m.group(2)
        new_tokens = []
        for tok in content.split(" "):
            core = tok.strip(_TOKEN_WRAP)
            repl = mapping.get(core)
            if core and repl is not None:
                idx = tok.find(core)
                tok = tok[:idx] + repl + tok[idx + len(core):]
            new_tokens.append(tok)
        out.append(prefix + " ".join(new_tokens))
    return "\n".join(out)


def clean_inline(s: str) -> str:
    """Sanitize a single-line value (e.g. a ToC title): drop all control chars."""
    if not s:
        return ""
    return _CTRL_ALL.sub("", s).strip()


def clean_block(s: str) -> str:
    """Sanitize multi-line body text: drop control chars but keep tabs/newlines."""
    if not s:
        return ""
    return _CTRL_KEEP_WS.sub("", s)


def _is_page_number(s: str, page_count: Optional[int]) -> bool:
    """True if `s` is a bare page number (and within the document's page range)."""
    m = _PAGE_NUM.match(s.strip())
    if not m:
        return False
    if page_count is None:
        return True
    return int(m.group(1)) <= page_count


def _split_cells(row: str) -> List[str]:
    """Split a markdown table row into trimmed cells (drop the outer pipes)."""
    r = row.strip()
    if r.startswith("|"):
        r = r[1:]
    if r.endswith("|"):
        r = r[:-1]
    return [c.strip() for c in r.split("|")]


def _row_has_content(row: str) -> bool:
    """True if a table row has at least one non-empty cell."""
    return any(_split_cells(row))


def _is_excision_residue(s: str) -> bool:
    """True if `s` (a line *after* boilerplate excision) is nothing but leftover
    furniture: whitespace, ``<br>`` tokens, and/or a single bare page number.
    Such a line only existed to carry the artifact, so it is dropped. This is
    independent of `strip_page_numbers` -- it triggers only because excision
    already happened on the line."""
    t = _BR.sub(" ", s).strip()
    return t == "" or bool(re.fullmatch(r"\d{1,4}", t))


def normalize_body(
    text: str,
    *,
    boilerplate_patterns: Iterable[str] = (),
    strip_page_numbers: bool = True,
    page_count: Optional[int] = None,
) -> str:
    """Strip recurring PDF artifacts from extracted body markdown. Idempotent.

    - ``boilerplate_patterns``: regex strings (e.g. a DRM ownership line). A line
      that is *only* boilerplate is dropped; a fragment matched inside a longer
      line (or table cell) is excised in place, and the line is dropped only if
      excision left nothing but furniture (whitespace / ``<br>`` / a bare page
      number). Interior double-spaces created by mid-line excision collapse to one.
    - ``strip_page_numbers``: drop *standalone* page-number lines (a whole line
      that is only a page number), bounded by ``page_count`` so a legitimate
      number larger than the document's page count is preserved.

    Table rows are NEVER removed on a numeric/empty heuristic -- a single-cell
    numeric row may be a subtotal, and an all-empty row may be a blank form
    field. The only row removal is a row we *emptied ourselves* via boilerplate
    excision. Conservative by design: see the module docstring.

    ``collapse_spaced_caps`` normalizes spaced-letter PDF font artifacts, but
    only on markdown heading lines -- never on code or table/stat rows -- so a
    single-letter stat column run is never mistaken for a spaced-out word.
    """
    if not text:
        return ""
    patterns: List[Pattern[str]] = [re.compile(p) for p in boilerplate_patterns]
    out: List[str] = []
    in_code = False
    for line in text.split("\n"):
        # Never touch fenced code-block content (or the fences themselves).
        if line.lstrip().startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue

        # Collapse spaced-out uppercase letter sequences (PDF font artifact),
        # e.g. "## C H A P T E R  F O U R" -> "## CHAPTER FOUR". Scoped to
        # markdown heading lines only: a stat/data row like Necromunda's
        # "M WS BS S T W I A Ld Cl Wil Int" contains a single-letter sub-run
        # that this collapse cannot distinguish from a spaced word, so we never
        # run it on non-heading lines.
        if line.lstrip().startswith("#"):
            line = collapse_spaced_caps(line)

        # 1. Excise boilerplate fragments anywhere in the line (incl. table cells).
        cleaned = line
        for pat in patterns:
            cleaned = pat.sub("", cleaned)
        excised = cleaned != line
        if excised:
            cleaned = _INNER_SPACES.sub(" ", cleaned)

        if cleaned.lstrip().startswith("|"):
            # 2. Table row: drop only a row we ourselves emptied (pure boilerplate).
            if excised and not _row_has_content(cleaned):
                continue
            out.append(cleaned)
            continue

        # 3. A non-table line reduced to furniture by excision: drop it.
        if excised and _is_excision_residue(cleaned):
            continue
        # 4. A standalone page-number line (no boilerplate involved).
        if strip_page_numbers and _is_page_number(cleaned, page_count):
            continue
        out.append(cleaned)

    return _BLANK_RUN.sub("\n\n", "\n".join(out))


# --- Necromunda stat-profile reformatting (opt-in) -------------------------
# Necromunda characteristic profiles are fixed 12-column rows. PDFs frequently
# render a profile -- together with the name/cost above it -- as one run-on TEXT
# line rather than a ruled table, so neither pymupdf4llm's "lines_strict" nor
# "text" table detection turns it into a grid. This opt-in pass (Necromunda
# config flag) reformats ONLY those exact shapes into a markdown table. Two
# canonical profiles are recognized:
#   - fighter:  M WS BS S T W I A Ld Cl Wil Int
#   - vehicle:  M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int
# Both are 12 columns, both end in "Wil Int", and both share one value grammar
# (``_STAT_VALUE``). The two headers are mutually exclusive (after "M" a fighter
# has "WS", a vehicle has "Front"), so detection cannot ambiguously match.
#
# The pass is deliberately narrow and additive: it never touches a line that is
# already a table row (starts with "|") or a heading, and it aborts on any line
# whose 12 post-header tokens are not all valid characteristic values -- so it
# can neither corrupt prose nor disturb the profiles pymupdf4llm already tabled.
_FIGHTER_COLS = ["M", "WS", "BS", "S", "T", "W", "I", "A", "Ld", "Cl", "Wil", "Int"]
_VEHICLE_COLS = ["M", "Front", "Side", "Rear", "HP", "Hnd", "Sv", "BS", "Ld", "Cl", "Wil", "Int"]


def _profile_header(cols: List[str]) -> Pattern[str]:
    """Build a header matcher for a profile's columns: the column run, optionally
    **bold**, with values optionally split off by ``<br>`` (normalized to a space
    before matching). Reproduces the original fighter pattern exactly for
    ``_FIGHTER_COLS`` -- the refactor is behavior-preserving for fighters."""
    return re.compile(r"\*{0,2}\s*" + r"\s+".join(cols) + r"\s*\*{0,2}")


# Ordered list of recognized profiles: (column labels, header matcher).
_STAT_PROFILES = [
    (_FIGHTER_COLS, _profile_header(_FIGHTER_COLS)),
    (_VEHICLE_COLS, _profile_header(_VEHICLE_COLS)),
]
# One characteristic value: movement (4"), target number (4+, 10+), a bare
# integer, or a dash for N/A. A trailing '*' is tolerated defensively.
_STAT_VALUE = re.compile(r'^(?:\d+["\u201d]|\d+\+|\d+|-)\*?$')
_DOTTED_LEADER = re.compile(r"\.{3,}")


def reformat_stat_profiles(text: str) -> str:
    """Reformat run-on Necromunda stat profiles into markdown tables.

    A line is rewritten only when it contains one of the canonical 12-column
    headers -- fighter (``M WS BS S T W I A Ld Cl Wil Int``) or vehicle
    (``M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int``), optionally bold, values
    optionally separated from the header by ``<br>`` -- immediately followed by
    exactly 12 valid characteristic values. Such a line becomes a name/cost line
    (if any), a 12-column markdown table, and any trailing text -- each on its
    own line.

    Idempotent and conservative: lines already starting with ``|`` or ``#`` pass
    through untouched, and any line whose 12 post-header tokens are not all valid
    values is left exactly as-is (never partially split). Pure; no I/O.
    """
    if not text or "Wil Int" not in text:
        return text
    out: List[str] = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("|") or stripped.startswith("#"):
            out.append(line)
            continue
        probe = _BR.sub(" ", line)
        cols = values = None
        prefix_src = suffix = ""
        for candidate_cols, header in _STAT_PROFILES:
            m = header.search(probe)
            if not m:
                continue
            tokens = probe[m.end():].split()
            if len(tokens) < 12 or not all(_STAT_VALUE.match(t) for t in tokens[:12]):
                continue
            cols = candidate_cols
            values = tokens[:12]
            suffix = " ".join(tokens[12:]).strip(" *")
            prefix_src = probe[: m.start()]
            break
        if cols is None:
            out.append(line)
            continue
        prefix = _DOTTED_LEADER.sub(" ", prefix_src)
        prefix = _INNER_SPACES.sub(" ", prefix).strip(" *")
        if prefix:
            out.append(prefix)
        out.append("")
        out.append("| " + " | ".join(cols) + " |")
        out.append("|" + "|".join(["---"] * len(cols)) + "|")
        out.append("| " + " | ".join(values) + " |")
        if suffix:
            out.append("")
            out.append(suffix)
    return _BLANK_RUN.sub("\n\n", "\n".join(out))


# --- Wrapped table-row merging (opt-in) ------------------------------------
# Necromunda weapon reference charts (per-house weaponry + the Trading Post)
# extract as valid-but-ugly markdown tables: a long trailing list (the `Traits`
# column, sometimes fused with `Am`) overflows onto a *following* row whose only
# non-empty cell is that column, while the row above ends that cell with a
# trailing comma. Obsidian renders the overflow as a near-blank row that splits
# each weapon's traits in two. This opt-in pass folds such continuation rows
# back into the preceding row. It re-joins text already present -- it never
# edits spelling, relabels headers, or invents content (fabrication ban).
#
# Detection is header-INDEPENDENT (by design): pymupdf4llm is inconsistent about
# whether it keeps `Am` and `Traits` as separate columns or fuses them, so the
# wrapped cell's index varies between sibling sub-tables. Instead of trusting a
# header label, a row is a continuation iff it has exactly ONE non-empty cell
# and the previous row's cell in that SAME column EITHER (a) ends with a comma --
# the usual line-wrap signal -- OR (b) ends with the first word of a known
# two-word Necromunda trait that the continuation cell completes (e.g.
# "...Knockback, Shield" + "Breaker, Shock" -> "Shield Breaker"; the comma falls
# *inside* the trait so case (a) misses it). This is still narrow and safe: a
# point-total subtotal (value in the Cost column), a blank form row (no non-empty
# cell), a section-label row, and a wrapped weapon *name* all fail the test. A
# >= 6-column block guard keeps it off small narrative tables. Idempotent: one
# pass removes every continuation row.
_SEP_CELL = re.compile(r"^:?-{3,}:?$")

# Real Necromunda two-word weapon traits (from the core rulebook trait glossary,
# section 1.60). Used ONLY to recognise a mid-trait line wrap that carries no
# trailing comma, so the split phrase can be rejoined. The join re-stitches text
# already present; it never invents a trait that was not in the cell.
_MULTIWORD_TRAITS = frozenset(
    {
        "Assault Shield",
        "Energy Shield",
        "Chem Delivery",
        "Graviton Pulse",
        "Rapid Fire",
        "Shield Breaker",
        "Single Shot",
    }
)
_TRAIT_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


def _is_separator_row(cells: List[str]) -> bool:
    non_empty = [c for c in cells if c]
    return bool(non_empty) and all(_SEP_CELL.match(c) for c in non_empty)


def _is_multiword_trait_wrap(prev_cell: str, cont_cell: str) -> bool:
    """True if the previous cell's last word + the continuation cell's first word
    form a known two-word trait split across a line wrap (no comma to signal it).
    Purely a detector for case (b) above; it does not modify either cell."""
    pw = _TRAIT_WORD.findall(prev_cell)
    cw = _TRAIT_WORD.findall(cont_cell)
    if not pw or not cw:
        return False
    return f"{pw[-1]} {cw[0]}" in _MULTIWORD_TRAITS


def _merge_table_block(rows: List[str]) -> List[str]:
    """Merge wrapped continuation rows within one table block (list of raw `|`
    lines). Returns the rewritten block; unchanged rows are emitted verbatim."""
    parsed = [_split_cells(r) for r in rows]
    # Block guard: weapon charts are 10-12 columns wide. Skip narrow tables where
    # a comma-ending cell + single-cell row is more likely to be real content.
    if max((len(c) for c in parsed), default=0) < 6:
        return rows

    kept_lines: List[str] = []
    kept_cells: List[Optional[List[str]]] = []
    prev_real = None  # index into kept_* of the last real data row
    dirty: set = set()
    for raw, cells in zip(rows, parsed):
        if _is_separator_row(cells):
            kept_lines.append(raw)
            kept_cells.append(None)
            continue
        non_empty = [k for k, c in enumerate(cells) if c != ""]
        is_continuation = False
        if (
            len(non_empty) == 1
            and prev_real is not None
            and kept_cells[prev_real] is not None
            and non_empty[0] < len(kept_cells[prev_real])
        ):
            k = non_empty[0]
            prev_cell = kept_cells[prev_real][k]
            is_continuation = prev_cell.endswith(",") or _is_multiword_trait_wrap(
                prev_cell, cells[k]
            )
        if is_continuation:
            k = non_empty[0]
            kept_cells[prev_real][k] += " " + cells[k]
            dirty.add(prev_real)
            continue  # drop the continuation row
        kept_lines.append(raw)
        kept_cells.append(cells)
        prev_real = len(kept_lines) - 1

    return [
        "|" + "|".join(kept_cells[i]) + "|" if i in dirty else raw
        for i, raw in enumerate(kept_lines)
    ]


def merge_wrapped_table_rows(text: str) -> str:
    """Fold wrapped continuation rows in weapon charts back into the row above.
    Block-aware, pure, idempotent; skips fenced code. Only ever *removes* a
    continuation row and extends the preceding row's cell -- see the module
    comment for the (deliberately narrow, header-independent) match rule."""
    if not text or "|" not in text:
        return text
    out: List[str] = []
    block: List[str] = []
    in_code = False
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith("```"):
            if block:
                out.extend(_merge_table_block(block))
                block = []
            in_code = not in_code
            out.append(line)
            continue
        if not in_code and s.startswith("|"):
            block.append(line)
            continue
        if block:
            out.extend(_merge_table_block(block))
            block = []
        out.append(line)
    if block:
        out.extend(_merge_table_block(block))
    return "\n".join(out)


# --- Structural table normalizers (opt-in, guarded) ------------------------
# Weapon-chart cleanups, all pure / idempotent / block-aware and all protected by
# `lib.table_guard.data_drift` when wired into extract.py: they only ever move
# LAYOUT, never data. Each transforms one table block (a list of raw `|` lines)
# and is applied through `_apply_to_table_blocks`, which mirrors the fenced-code-
# aware block walk used by `merge_wrapped_table_rows`.
#
#   promote_header_below_separator -- fix a misplaced header: pymupdf4llm often
#       emits weapon charts as `group-row | separator | label-row`, i.e. the
#       markdown header is a near-empty spanning row (`|Rng|Rng|Acc|Acc|...`),
#       the separator follows it, and the REAL column labels (`|Weapon|S|L|...`)
#       land below the separator as the first data row. Obsidian then treats the
#       near-empty group row as the header and refuses to render a proper table.
#       This folds the group row + the demoted label row into one real header
#       above the separator, dropping the label row from the data region. The
#       data guard recognises this exact shape (via `_is_demoted_header_table`)
#       so the relocation is NOT flagged as a dropped data token.
#   promote_demoted_label_row -- same demoted-label shape on small (2-5 column)
#       benefit tables (`|Selections||| / sep / |Available|...|Cost|`): promote
#       the real label row above the separator and emit the spanning group title
#       as `**title**` prose immediately above the table (Obsidian has no colspan).
#       Guarded via `_is_demoted_label_row_table`; runs on every clean-tier build.
#   collapse_table_headers  -- fold a two-row (group + sub) header into one (the
#       rarer shape where BOTH header rows sit above the separator, at index 2).
#   split_am_traits         -- split a fused `Am Traits` column into two.
#   merge_wrapped_name_rows -- fold an orphan weapon-name row into the name above.
#
# The >= 6-column block guard keeps all of these off small narrative tables,
# exactly like the wrapped-row merge. Header relabeling/promotion and column
# splitting are token-preserving in the DATA region (the guard's view of it);
# name merges re-join text already present. The guard hard-fails the build if any
# of that is ever false.

# Leading "Ammo" token of a fused `Am Traits` cell: a roll target (`5+`), a flat
# number, or `-` (no ammo). Everything after it is the trait list.
_AM_TOKEN = re.compile(r"^(\d+\+|\d+|-)(?:\s+(.*))?$")
_AM_TRAITS_HEADER = re.compile(r"^Am\s+Traits$", re.IGNORECASE)


def _apply_to_table_blocks(text: str, fn) -> str:
    """Run `fn(block) -> List[str]` over every table block, skipping fenced code.
    Shared block walk for the structural normalizers."""
    if not text or "|" not in text:
        return text
    out: List[str] = []
    block: List[str] = []
    in_code = False
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith("```"):
            if block:
                out.extend(fn(block))
                block = []
            in_code = not in_code
            out.append(line)
            continue
        if not in_code and s.startswith("|"):
            block.append(line)
            continue
        if block:
            out.extend(fn(block))
            block = []
        out.append(line)
    if block:
        out.extend(fn(block))
    return "\n".join(out)


def _sep_index(parsed: List[List[str]]) -> Optional[int]:
    for i, cells in enumerate(parsed):
        if _is_separator_row(cells):
            return i
    return None


def _is_demoted_header_table(parsed: List[List[str]]) -> bool:
    """True for the `group-row | separator | label-row` weapon-chart shape, where
    the real column header was pushed below the separator into the data region.

    Detection is deliberately tight (and gated/Necromunda-scoped at the call
    site): a >= 6-column block whose separator sits at row index 1, whose markdown
    header (row 0) has an EMPTY first cell (the spanning group row), and whose
    first data row (row 2) is itself a weapon-chart column header -- it shares the
    group row's column count, has a non-empty first cell (the item-type label,
    e.g. `Weapon` / `Grenade`), and carries the literal stat-column header labels
    (`AP` and `D`, plus `Am` and/or `Traits`, matched case-insensitively and with
    any markdown bold markers stripped -- real PDFs render this column `Ap`,
    `AP`, or bold `**Ap**` depending on source). Those header WORDS never appear
    in a data row (data rows hold values like `-1`, `4+`), so this will not fire
    on a genuine data row. This is the single predicate shared by
    `_promote_header_block` (which rewrites the table) and
    `lib.table_guard._data_rows` (which therefore excludes the demoted label row
    from the data region, so promotion is not seen as a dropped data token)."""
    if len(parsed) < 3:
        return False
    if max((len(c) for c in parsed), default=0) < 6:
        return False
    if not _is_separator_row(parsed[1]):
        return False
    group, labels = parsed[0], parsed[2]
    if len(group) != len(labels):
        return False
    if group[0].strip() != "":
        return False
    if labels[0].strip() == "":  # the item-type label (Weapon/Grenade/...) must be present
        return False
    label_set = {c.strip().strip("*").strip().upper() for c in labels}
    has_stats = "AP" in label_set and "D" in label_set
    has_ammo_or_traits = bool(label_set & {"AM", "TRAITS", "AM TRAITS"})
    return has_stats and has_ammo_or_traits


# First-column patterns on small narrative tables (data rows), not headers.
# Benefit/patronage: ``0-5``, ``Unlimited``; collision damage: ``3"-5"``, ``10"+``.
_LABEL_ROW_DATA_FIRST = re.compile(
    r'^(?:Unlimited|\d+-\d+|\d+|'
    r'\d+["\u201d]-\d+["\u201d]|\d+["\u201d]\+)$',
    re.IGNORECASE,
)


def _is_demoted_label_row_table(parsed: List[List[str]]) -> bool:
    """True for small narrative tables in the `group-row | separator | label-row`
    shape where the real column header was pushed below the separator.

    Unlike the weapon-chart demoted header (``_is_demoted_header_table``), the
    spanning group row here carries its title in the *first* cell with the rest
    empty (``|Selections|||``), and the label row is a fully populated header
    (``|Available|House Patronage Benefit|Cost|``). Detection is limited to 2-5
    columns and requires at least one following data row whose first cell looks
    like a benefit-table constraint (``0-5``, ``Unlimited``, …) or a movement
    range (``3"-5"``, ``10"+``), not a header word. Shared by
    ``promote_demoted_label_row`` and ``table_guard._data_rows``."""
    if len(parsed) < 4:
        return False
    if _is_demoted_header_table(parsed):
        return False
    ncols = max((len(c) for c in parsed), default=0)
    if ncols < 2 or ncols > 5:
        return False
    if not _is_separator_row(parsed[1]):
        return False
    group, labels = parsed[0], parsed[2]
    if len(group) != ncols or len(labels) != ncols:
        return False
    if not group[0].strip():
        return False
    if not all(not c.strip() for c in group[1:]):
        return False
    if not all(c.strip() for c in labels):
        return False
    if _LABEL_ROW_DATA_FIRST.match(labels[0].strip()):
        return False
    if not _LABEL_ROW_DATA_FIRST.match(parsed[3][0].strip()):
        return False
    return True


def _promote_label_row_block(rows: List[str]) -> tuple[List[str], List[str]]:
    """Promote a demoted label row (see ``_is_demoted_label_row_table``).

    Returns ``(prefix_lines, table_rows)``. When the group row is a single-cell
    spanning title, it becomes a ``**title**`` line immediately above the table
    (Obsidian has no colspan). The label row moves above the separator; data
    rows are untouched."""
    parsed = [_split_cells(r) for r in rows]
    if not _is_demoted_label_row_table(parsed):
        return [], rows
    title = parsed[0][0].strip().strip("*")
    prefix = [f"**{title}**"] if title else []
    return prefix, [rows[2], rows[1]] + rows[3:]


def _promote_header_block(rows: List[str]) -> List[str]:
    """Promote a demoted weapon-chart header (see `_is_demoted_header_table`).

    Merges the spanning group row (row 0) and the real label row (row 2)
    positionally into one header above the separator -- `Rng` over `S` -> `Rng
    (S)`, empty group cell -> the bare label -- then drops the now-promoted label
    row from the data region. Column count is preserved, so the table stays
    rectangular. Idempotent: once row 0 starts with `Weapon`, the shape no longer
    matches and the block is returned unchanged."""
    parsed = [_split_cells(r) for r in rows]
    if not _is_demoted_header_table(parsed):
        return rows
    group, labels = parsed[0], parsed[2]
    merged: List[str] = []
    for g, h in zip(group, labels):
        g, h = g.strip(), h.strip()
        if g and h and g != h:
            merged.append(f"{g} ({h})")
        elif h:
            merged.append(h)
        elif g:
            merged.append(g)
        else:
            merged.append("")
    # new header, keep the separator (rows[1]), drop the label row (rows[2]).
    return ["|" + "|".join(merged) + "|", rows[1]] + rows[3:]


def _collapse_header_block(rows: List[str]) -> List[str]:
    """Fold a two-row header (group row directly above the real header) into one.

    A normal markdown table has its separator at row index 1. pymupdf4llm emits a
    *spanning* group header as an extra row above the real header, pushing the
    separator to index 2 (`Range|Range|Accuracy|...` over `S|L|S|...`). When that
    shape is seen, each column becomes `Group (Sub)` (`Range` over `S` -> `Range
    (S)`); equal/half-empty pairs collapse to the present label. If the two header
    rows do not share a column count, the group row is simply dropped. DATA rows
    are never touched, so the guard sees no drift."""
    parsed = [_split_cells(r) for r in rows]
    if max((len(c) for c in parsed), default=0) < 6:
        return rows
    if _sep_index(parsed) != 2:  # not a two-row-header table
        return rows
    group, header = parsed[0], parsed[1]
    if len(group) != len(header):  # cannot align -> drop the group row
        return rows[1:]
    merged: List[str] = []
    for g, h in zip(group, header):
        g, h = g.strip(), h.strip()
        if g and h and g != h:
            merged.append(f"{g} ({h})")
        elif g:
            merged.append(g)
        else:
            merged.append(h)
    return ["|" + "|".join(merged) + "|"] + rows[2:]


def _split_am_traits_block(rows: List[str]) -> List[str]:
    """Split a single fused `Am Traits` header column into separate `Am` and
    `Traits` columns across the header, separator, and every data row.

    The leading ammo token (`5+`, `2`, `-`) of each data cell becomes the `Am`
    cell; the remainder becomes `Traits` (no leading token => empty `Am`). The
    column count grows by exactly one everywhere, so the table stays rectangular
    and the `tables` gate stays green. Token-preserving in the data region."""
    parsed = [_split_cells(r) for r in rows]
    if max((len(c) for c in parsed), default=0) < 6:
        return rows
    sep = _sep_index(parsed)
    if sep is None:
        return rows
    header = parsed[0]
    cols = [j for j, c in enumerate(header) if _AM_TRAITS_HEADER.match(c.strip())]
    if len(cols) != 1:
        return rows
    j = cols[0]
    width = len(header)
    # Require a rectangular table so the inserted column stays aligned.
    if any(len(c) != width for c in parsed):
        return rows

    out: List[str] = []
    for idx, (raw, cells) in enumerate(zip(rows, parsed)):
        if idx == sep:
            new = cells[:j] + [cells[j], cells[j]] + cells[j + 1:]
        elif idx == 0:
            new = cells[:j] + ["Am", "Traits"] + cells[j + 1:]
        else:
            cell = cells[j].strip()
            m = _AM_TOKEN.match(cell)
            if m:
                am, traits = m.group(1), (m.group(2) or "")
            else:
                am, traits = "", cell
            new = cells[:j] + [am, traits] + cells[j + 1:]
        out.append("|" + "|".join(new) + "|")
    return out


def _is_name_subheader(cell: str) -> bool:
    """Denylist guarding `merge_wrapped_name_rows`: an orphan first-column cell
    that is really a sub-header (italic emphasis, a combi-weapon/component/pattern
    label, or an ALL-CAPS section heading), not a wrapped weapon name."""
    c = cell.strip()
    if not c:
        return True
    if c.startswith("*") or c.startswith("_"):  # italic / emphasis run
        return True
    cl = c.lower()
    if "combi-weapon" in cl or "component" in cl or "pattern" in cl:
        return True
    letters = [ch for ch in c if ch.isalpha()]
    if letters and all(ch.isupper() for ch in letters):  # ALL-CAPS section label
        return True
    return False


def _merge_name_block(rows: List[str]) -> List[str]:
    """Fold an orphan row whose only non-empty cell is the Weapon column (index 0)
    into the weapon name in the row above -- but only when that row above is a
    complete data row (carries stat values) and the orphan is not a sub-header.

    This rejoins names wrapped onto a second line (`- photon flash` + `grenades`).
    It is the most heuristic of the three rules; the guard is its safety net."""
    parsed = [_split_cells(r) for r in rows]
    if max((len(c) for c in parsed), default=0) < 6:
        return rows

    kept_lines: List[str] = []
    kept_cells: List[Optional[List[str]]] = []
    prev_real = None  # index into kept_* of last complete DATA row
    seen_sep = False
    dirty: set = set()
    for raw, cells in zip(rows, parsed):
        if _is_separator_row(cells):
            seen_sep = True
            kept_lines.append(raw)
            kept_cells.append(None)
            continue
        non_empty = [k for k, c in enumerate(cells) if c != ""]
        is_name_wrap = (
            seen_sep
            and non_empty == [0]
            and prev_real is not None
            and kept_cells[prev_real] is not None
            and sum(1 for c in kept_cells[prev_real] if c) >= 2
            and not _is_name_subheader(cells[0])
        )
        if is_name_wrap:
            kept_cells[prev_real][0] += " " + cells[0]
            dirty.add(prev_real)
            continue
        kept_lines.append(raw)
        kept_cells.append(cells)
        if seen_sep:
            prev_real = len(kept_lines) - 1

    return [
        "|" + "|".join(kept_cells[i]) + "|" if i in dirty else raw
        for i, raw in enumerate(kept_lines)
    ]


def promote_header_below_separator(text: str) -> str:
    """Fix a demoted weapon-chart header (`group-row | separator | label-row`) by
    folding the group row and the real label row into one header above the
    separator. Pure, idempotent, block-aware. The data guard recognises this
    shape (shared `_is_demoted_header_table`), so the relocation is not flagged."""
    return _apply_to_table_blocks(text, _promote_header_block)


def promote_demoted_label_row(text: str) -> str:
    """Fix a demoted benefit-table header (2-5 columns): promote the real label
    row above the separator and emit the spanning group title as ``**title**``
    prose immediately above the table. Pure, idempotent, block-aware. The data
    guard recognises this shape (shared ``_is_demoted_label_row_table``)."""
    if not text or "|" not in text:
        return text
    out: List[str] = []
    block: List[str] = []
    in_code = False
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith("```"):
            if block:
                prefix, promoted = _promote_label_row_block(block)
                if prefix:
                    if out and out[-1] != "":
                        out.append("")
                    out.extend(prefix)
                    out.append("")
                    out.extend(promoted)
                else:
                    out.extend(block)
                block = []
            in_code = not in_code
            out.append(line)
            continue
        if not in_code and s.startswith("|"):
            block.append(line)
            continue
        if block:
            prefix, promoted = _promote_label_row_block(block)
            if prefix:
                if out and out[-1] != "":
                    out.append("")
                out.extend(prefix)
                out.append("")
                out.extend(promoted)
            else:
                out.extend(block)
            block = []
        out.append(line)
    if block:
        prefix, promoted = _promote_label_row_block(block)
        if prefix:
            if out and out[-1] != "":
                out.append("")
            out.extend(prefix)
            out.append("")
            out.extend(promoted)
        else:
            out.extend(block)
    return "\n".join(out)


def collapse_table_headers(text: str) -> str:
    """Collapse two-row (group + sub) weapon-chart headers into one. Pure,
    idempotent, block-aware; header-only (data rows untouched)."""
    return _apply_to_table_blocks(text, _collapse_header_block)


def split_am_traits(text: str) -> str:
    """Split a fused `Am Traits` column into separate `Am` and `Traits` columns.
    Pure, idempotent, block-aware; keeps the table rectangular."""
    return _apply_to_table_blocks(text, _split_am_traits_block)


def merge_wrapped_name_rows(text: str) -> str:
    """Fold an orphan weapon-name continuation row into the name above. Pure,
    idempotent, block-aware; narrow denylist + the data guard keep it safe."""
    return _apply_to_table_blocks(text, _merge_name_block)
