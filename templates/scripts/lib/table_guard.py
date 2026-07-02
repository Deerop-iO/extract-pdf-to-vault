"""Deterministic table "diff-guard": prove a reformat changed no data.

Every structural table transform the kit applies (row merges, an ``Am``/``Traits``
column split, a two-row header collapse, or a human/agent hand-edit) is supposed
to change only *layout*, never the data. This module makes that checkable.

The enforced invariant is: **the multiset of whitespace-split tokens in a table's
DATA rows is preserved.** Header rows are exempt (so relabeling a header -- e.g.
``S`` -> ``Range (S)`` -- is free), and pure layout moves keep every data token:

- row merge: ``Blaze, Rapid Fire (1),`` + ``Shock`` -> ``Blaze, Rapid Fire (1), Shock``
- column split: ``5+ Blaze, Combi`` -> ``5+`` | ``Blaze, Combi``
- name-wrap merge: ``- photon flash`` + ``grenades`` -> ``- photon flash grenades``

Any token added, dropped, or altered in the data region is real content drift
(fabrication) and is reported. The comparison is per-table, in document order.

Limitation (documented, accepted): the default ``data_drift`` invariant is a
multiset, so a pure *reordering* of data rows is not detected -- the
deterministic normalizers never reorder, so this is safe for the pipeline. For
agent/hand edits (which *could* reorder), use ``data_drift_strict`` (below): it
enforces the multiset invariant AND additionally flags a data-row *permutation*
(the rows' anchor cells kept as a set but shuffled). This catches a row swap --
the realistic agent mistake -- while still permitting the legitimate layout edits
(row merge, column split, header promotion, name-wrap merge), which change the
anchor set or its length rather than merely reordering it. A pure ordered-token
sequence was rejected here because a mid-table wrapped-column merge legitimately
moves a continuation token ahead of trailing columns. A change to the number of
tables is reported as drift by both.

Pure; no I/O. Cell parsing and separator detection are reused from ``lib.text``
so the guard sees tables exactly as the rest of the kit does.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterator, List

from .text import _split_cells, _is_separator_row, _is_demoted_header_table, _is_demoted_label_row_table


def _iter_table_blocks(lines: List[str]) -> Iterator[List[str]]:
    """Yield runs of consecutive table rows (lines starting with ``|``), skipping
    fenced code blocks. Mirrors ``verify_vault._iter_table_blocks``."""
    block: List[str] = []
    in_code = False
    for line in lines:
        s = line.lstrip()
        if s.startswith("```"):
            in_code = not in_code
            if block:
                yield block
                block = []
            continue
        if not in_code and s.startswith("|"):
            block.append(line)
        elif block:
            yield block
            block = []
    if block:
        yield block


def _data_rows(block: List[str]) -> List[str]:
    """Rows after the separator row -- the data region. The header region (every
    row up to and including the ``|---|`` separator) is exempt from the guard. A
    block with no separator (degenerate/malformed) is treated as all-data.

    Exception: for the demoted-header shape (`group-row | separator | label-row`,
    see ``lib.text._is_demoted_header_table``), the row immediately after the
    separator is the REAL column header that pymupdf4llm pushed below the
    separator. It is excluded from the data region too, so that
    ``promote_header_below_separator`` relocating it into the header reads as a
    header move, not a dropped data token. This keeps the guard and the rule in
    lockstep via the one shared predicate."""
    parsed = [_split_cells(r) for r in block]
    if _is_demoted_header_table(parsed):
        return block[3:]  # skip group row, separator, AND the demoted label row
    if _is_demoted_label_row_table(parsed):
        return block[3:]  # skip spanning group row, separator, AND the demoted label row
    for i, cells in enumerate(parsed):
        if _is_separator_row(cells):
            return block[i + 1:]
    return block


def _table_data_tokens(md: str) -> List[Counter]:
    """One ``Counter`` of whitespace-split data-cell tokens per table, in
    document order."""
    tables: List[Counter] = []
    for block in _iter_table_blocks(md.split("\n")):
        tokens: Counter = Counter()
        for row in _data_rows(block):
            for cell in _split_cells(row):
                tokens.update(cell.split())
        tables.append(tokens)
    return tables


def _table_row_anchors(md: str) -> List[List[str]]:
    """Per table, the ordered list of data-row *anchors*: the first cell of each
    data row whose first cell is non-empty.

    Continuation rows (empty first cell) -- wrapped-column continuations and
    single-cell subtotals -- are skipped, so folding them into a neighbour is
    invisible to this order check. A genuine row swap, in contrast, permutes the
    anchors. Header rows use the same exemption as ``_data_rows``."""
    tables: List[List[str]] = []
    for block in _iter_table_blocks(md.split("\n")):
        anchors: List[str] = []
        for row in _data_rows(block):
            cells = _split_cells(row)
            first = cells[0].strip() if cells else ""
            if first:
                anchors.append(first)
        tables.append(anchors)
    return tables


def _first_divergence(before: List[str], after: List[str]) -> int:
    """Index of the first differing element (or the shorter length if one is a
    prefix of the other). Callers only invoke this when the lists differ."""
    i = 0
    for i, (x, y) in enumerate(zip(before, after)):
        if x != y:
            return i
    return min(len(before), len(after))


def data_drift_strict(before: str, after: str) -> List[str]:
    """Strict invariant for agent/hand table edits.

    Enforces the loose multiset invariant (no data token added, dropped, or
    altered) AND additionally flags a data-row *permutation*: rows whose anchor
    cells are preserved as a set but shuffled into a different order (a row swap).

    It deliberately permits the legitimate layout edits -- row merge, column
    split, header promotion, name-wrap merge -- because those change the anchor
    set or its length rather than merely reordering it, and the multiset check
    still guarantees no data was lost. Use it for the `/p2v-repair-document`
    skill's table repairs; the pipeline normalizers keep the looser ``data_drift``.

    Returns human-readable drift messages (empty == no drift)."""
    messages = list(data_drift(before, after))
    if any("table count changed" in m for m in messages):
        return messages  # cannot align tables to check row order
    ba = _table_row_anchors(before)
    aa = _table_row_anchors(after)
    for i, (b, a) in enumerate(zip(ba, aa), start=1):
        if b != a and sorted(b) == sorted(a):
            j = _first_divergence(b, a)
            bx = b[j] if j < len(b) else "<end>"
            ax = a[j] if j < len(a) else "<end>"
            messages.append(
                f"table #{i}: data row order changed at position {j}: "
                f"{bx!r} -> {ax!r}"
            )
    return messages


def _fmt(counter: Counter) -> str:
    return ", ".join(f"{tok!r}x{n}" for tok, n in sorted(counter.items()))


def data_drift(before: str, after: str) -> List[str]:
    """Return a list of human-readable drift messages (empty == no drift).

    Compares ``before`` and ``after`` table-by-table on their data-row token
    multisets. Reports a table-count change, and per table any tokens dropped
    (in before, not after) or added (in after, not before)."""
    bt = _table_data_tokens(before)
    at = _table_data_tokens(after)
    if len(bt) != len(at):
        return [f"table count changed: {len(bt)} -> {len(at)} (cannot align to diff)"]
    messages: List[str] = []
    for i, (b, a) in enumerate(zip(bt, at), start=1):
        if b == a:
            continue
        dropped = b - a
        added = a - b
        parts = []
        if dropped:
            parts.append(f"dropped {_fmt(dropped)}")
        if added:
            parts.append(f"added {_fmt(added)}")
        messages.append(f"table #{i}: " + "; ".join(parts))
    return messages
