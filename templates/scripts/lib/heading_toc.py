"""Reconstruct a synthetic ToC from markdown headings (no-ToC fallback).

Pure and deterministic (no PDF access): the caller passes the already-extracted,
already-normalized per-page markdown bodies, and this returns a raw
``[[level, title, start_page], ...]`` list in the same shape ``get_toc()`` and
``_synthetic_toc_from_pages`` produce, ready for ``toc_tree.build_sections``.

Only used when a PDF has no embedded table of contents and the operator opts in
via ``--fallback headings``. The headings themselves come from pymupdf4llm's own
layout/font-size classifier (a ``title`` box -> ``# ``, a ``section-header`` box
-> ``## ``), so we never invent a hierarchy -- we only harvest what the extractor
already emitted.
"""

from __future__ import annotations

import re
from typing import List

from .text import clean_inline

# A markdown ATX heading line: capture the content after the `#` run.
_HEADING = re.compile(r"^#{1,6}\s+(.+)$")
# A fenced-code delimiter (``` or ~~~), possibly indented / with an info string.
_FENCE = re.compile(r"^\s*(```|~~~)")
# Emphasis / code wrappers that pymupdf4llm may leave around a heading token.
_EMPHASIS = re.compile(r"[*_`]+")


def _first_heading(text: str) -> str:
    """Return the first real markdown heading title on a page, or ``""``.

    Fenced code blocks are skipped: a ``#`` line inside a ```` ``` ```` fence is a
    comment/shell line pymupdf4llm emitted for a monospaced block, not a heading
    (mirrors ``verify_vault.check_heading_artifacts`` / ``_iter_table_blocks``).
    """
    in_code = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = _HEADING.match(line.strip())
        if not m:
            continue
        title = clean_inline(_EMPHASIS.sub("", m.group(1)))
        if title:
            return title
    return ""


def toc_from_headings(page_texts: List[str]) -> list:
    """Build a synthetic flat ``[[1, title, page], ...]`` ToC from page markdown.

    ``page_texts[i]`` is page ``i + 1``'s (post-normalization) markdown body.

    Flat by design: every heading -> level 1, regardless of pymupdf4llm's
    ``#``-count -- a nested hierarchy is not reliably derivable from this signal,
    and passing the raw levels through would nest the whole document under its
    first heading. At most one entry per page (the first heading found), since a
    page is the smallest unit this pipeline can split on; extra same-page
    headings would only duplicate the page's body across notes. If the first
    heading is not on page 1, a leading ``Pages 1-N`` entry captures the pages
    before it so no content is silently dropped. Returns ``[]`` when no page has
    a usable heading line (the caller hard-stops).
    """
    entries: list = []
    for i, text in enumerate(page_texts):
        page = i + 1
        title = _first_heading(text or "")
        if title:
            entries.append([1, title, page])

    if not entries:
        return []

    first_page = entries[0][2]
    if first_page > 1:
        label = "Page 1" if first_page == 2 else f"Pages 1-{first_page - 1}"
        entries.insert(0, [1, label, 1])
    return entries
