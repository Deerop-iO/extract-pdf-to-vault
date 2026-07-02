"""Reconstruct a back-of-book alphabetical index from PDF glyph geometry.

A printed index is laid out in N columns, each an independent A-Z stream of
``term .... page-numbers`` rows. A flat text/markdown extractor reads each
printed line left-to-right *across* the columns and concatenates, which both
glues unrelated entries onto one line and scrambles the letter order (the true
reading order is column-by-column, not row-by-row). pymupdf4llm also leaks the
big "INDEX" title, running headers/footers, and image alt-text into the body.

This module rebuilds the index from positioned text fragments:

1. Pick a *column template* -- the column band layout from whichever index page
   detects the cleanest (most) columns -- and apply it to every index page, so
   pages whose gutters are bridged by dotted leaders still split correctly.
2. Keep only fragments at the dominant (entry) font size, which drops the title,
   the page-number footer, and the running header without guesswork.
3. Within each column, group fragments into rows by baseline and read top to
   bottom; emit columns left-to-right, pages in order -- i.e. true A-Z order.
4. Strip dotted leaders, classify single-letter rows as section headings, and
   emit one entry per line.

Everything here is geometry-driven reformatting of already-extracted text: it
never invents a term, a page number, or an ordering the page does not contain.
The result keeps the literal page numbers (faithful to the book); turning those
numbers into vault wikilinks is the build stage's job.

Input is a list of *pages*, each a list of fragment dicts:
``{"text": str, "x0": float, "x1": float, "y": float, "size": float,
"bold": bool}``. Pure (no PyMuPDF), so it is unit-testable with synthetic data.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional

# A run that is only dotted-leader characters (or dots glued to nothing useful).
_DOT_RUN = re.compile(r"[.\u00b7\u2026]{2,}")
# A single capital letter, optionally bracketed/emphasised -- an index A..Z head.
_LETTER_HEAD = re.compile(r"^[*_]{0,2}([A-Z])[*_]{0,2}$")
# Trailing page-number group: digits with commas / ranges / spaces / bold markers.
_TRAILING_PAGES = re.compile(r"(?:\*{0,2}\d[\d,\u2013\-\s*]*)$")


def _detect_columns(frags: List[dict], min_gutter: float) -> List[tuple]:
    """Return column x-bands [(x0,x1),...] for one page via coverage gutters."""
    if not frags:
        return []
    lo = int(min(f["x0"] for f in frags))
    hi = int(max(f["x1"] for f in frags)) + 1
    cov = bytearray(hi - lo + 1)
    for f in frags:
        a, b = int(f["x0"]) - lo, int(f["x1"]) - lo
        for x in range(max(a, 0), min(b, len(cov) - 1) + 1):
            cov[x] = 1
    runs = []
    start = None
    for i, c in enumerate(cov):
        if not c and start is None:
            start = i
        elif c and start is not None:
            if i - start >= min_gutter:
                runs.append((lo + start, lo + i))
            start = None
    bands = []
    left = lo
    for g0, g1 in runs:
        bands.append((left, g0))
        left = g1
    bands.append((left, hi))
    return [(a, b) for a, b in bands if b - a > 40]


def _column_template(pages: List[List[dict]], min_gutter: float) -> List[tuple]:
    """Pick the richest (most-column) band layout across all index pages."""
    best: List[tuple] = []
    for frags in pages:
        bands = _detect_columns(frags, min_gutter)
        if len(bands) > len(best):
            best = bands
    return best


def _dominant_size(pages: List[List[dict]]) -> float:
    sizes = Counter(round(f["size"], 1) for frags in pages for f in frags if f["text"].strip())
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _cuts(bands: List[tuple]) -> List[float]:
    """Midpoint x between adjacent column bands -> assignment boundaries."""
    return [(bands[i][1] + bands[i + 1][0]) / 2 for i in range(len(bands) - 1)]


def _column_of(x0: float, cuts: List[float]) -> int:
    for i, cut in enumerate(cuts):
        if x0 < cut:
            return i
    return len(cuts)


def _strip_leaders(text: str) -> str:
    text = _DOT_RUN.sub(" ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)  # leaders leave " ," / " ." gaps
    return text.strip()


def _group_rows(frags: List[dict], y_tol: float) -> List[List[dict]]:
    """Cluster fragments into rows by baseline y, each row sorted left-to-right."""
    rows: List[List[dict]] = []
    for f in sorted(frags, key=lambda f: (f["y"], f["x0"])):
        if rows and abs(f["y"] - rows[-1][0]["y"]) <= y_tol:
            rows[-1].append(f)
        else:
            rows.append([f])
    for r in rows:
        r.sort(key=lambda f: f["x0"])
    return rows


def _row_text(row: List[dict]) -> str:
    parts = []
    for f in row:
        t = f["text"]
        if f.get("bold") and t.strip():
            t = f"**{t.strip()}**"
        parts.append(t)
    return _strip_leaders(" ".join(parts))


def reconstruct_index(
    pages: List[List[dict]],
    *,
    title: str = "",
    min_gutter: float = 12.0,
    y_tol: float = 4.0,
    size_tol: float = 0.6,
) -> Optional[str]:
    """Rebuild an index section's markdown from positioned fragments.

    Returns the markdown body (``## INDEX`` + per-letter ``###`` headings + one
    ``- entry`` per line, page numbers left as plain text for the build stage to
    linkify), or ``None`` if no column structure could be found (caller should
    then fall back to the normal extraction for that section).
    """
    pages = [[f for f in frags if f.get("text", "").strip()] for frags in pages]
    if not any(pages):
        return None
    bands = _column_template(pages, min_gutter)
    if len(bands) < 2:
        return None  # not a recognisable multi-column index
    cuts = _cuts(bands)
    x_lo, x_hi = bands[0][0] - 5, bands[-1][1] + 5
    dom = _dominant_size(pages)
    title_norm = title.strip().casefold()

    out: List[str] = ["## INDEX", ""]
    seen_letters: set = set()
    for frags in pages:
        # Keep dominant-size (entry) fragments, plus the larger single-letter
        # section heads (A, B, ...) which sit above the entry size; everything
        # else off-size (the giant "INDEX" title, footers) is dropped.
        kept = [
            f
            for f in frags
            if x_lo <= f["x0"] <= x_hi
            and (
                abs(round(f["size"], 1) - dom) <= size_tol
                or _LETTER_HEAD.match(f["text"].strip())
            )
        ]
        columns: List[List[dict]] = [[] for _ in range(len(bands))]
        for f in kept:
            columns[_column_of(f["x0"], cuts)].append(f)
        for col in columns:
            for row in _group_rows(col, y_tol):
                text = _row_text(row)
                if not text:
                    continue
                if text.strip().casefold() == title_norm or text.strip().upper() == "INDEX":
                    continue
                m = _LETTER_HEAD.match(text)
                if m:
                    letter = m.group(1)
                    if letter not in seen_letters:
                        seen_letters.add(letter)
                        if out and out[-1] != "":
                            out.append("")  # blank line before the heading
                        out.extend([f"### {letter}", ""])
                    continue
                out.append(f"- {text}")
    # Collapse any accidental empty trailing structure.
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n" if out else None
