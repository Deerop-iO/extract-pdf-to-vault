"""Turn a raw PyMuPDF ``get_toc()`` list into ordered section nodes.

Pure and deterministic (vault-contract.md, sections 2.2 and 5). No PDF access:
callers pass the raw ``[[level, title, start_page], ...]`` list plus page count.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .slugify import slugify

DEFAULT_PAD_WIDTH = 2


def _assign_counters(levels: List[int]) -> List[Tuple[int, ...]]:
    """Assign a positional counter tuple to each entry.

    A level may be at most one deeper than the current depth; deeper jumps are
    clamped so we never invent phantom parents (keeps numbering deterministic
    and parent references valid).
    """
    counters: List[int] = []
    out: List[Tuple[int, ...]] = []
    for level in levels:
        eff = min(max(level, 1), len(counters) + 1)
        counters = counters[:eff]
        if len(counters) < eff:
            counters.append(0)
        counters[eff - 1] += 1
        out.append(tuple(counters))
    return out


def _group_maxima(tuples: List[Tuple[int, ...]]) -> dict:
    """Max sibling index for every prefix group, to size zero-padding per group."""
    groups: dict = {}
    for tup in tuples:
        for i in range(len(tup)):
            prefix = tup[:i]
            groups[prefix] = max(groups.get(prefix, 0), tup[i])
    return groups


def _format_number(tup: Tuple[int, ...], groups: dict, pad_width: int) -> str:
    parts = []
    for i, seg in enumerate(tup):
        width = max(pad_width, len(str(groups.get(tup[:i], seg))))
        parts.append(str(seg).zfill(width))
    return ".".join(parts)


def _human_number(tup: Tuple[int, ...]) -> str:
    return ".".join(str(seg) for seg in tup)


def build_sections(
    toc: List[list],
    page_count: int,
    pad_width: int = DEFAULT_PAD_WIDTH,
    slug_max_len: int = 60,
) -> List[dict]:
    """Return an ordered, flat list of section node dicts.

    Each node: toc_number, parent_number, level, title, display_title, slug,
    is_leaf, start_page, end_page. ``markdown`` and ``assets`` are filled later
    by the extractor.
    """
    if not toc:
        return []

    levels = [int(entry[0]) for entry in toc]
    titles = [str(entry[1]) for entry in toc]
    start_pages = [int(entry[2]) for entry in toc]

    tuples = _assign_counters(levels)
    groups = _group_maxima(tuples)
    n = len(toc)

    sections: List[dict] = []
    for k in range(n):
        tup = tuples[k]
        eff_level = len(tup)
        number = _format_number(tup, groups, pad_width)
        parent_number = (
            _format_number(tup[:-1], groups, pad_width) if len(tup) > 1 else None
        )

        # A node is a branch if the next entry is one level deeper.
        is_leaf = not (k + 1 < n and len(tuples[k + 1]) > eff_level)

        # End page = (start of next entry at same-or-shallower level) - 1.
        end_page = page_count
        for j in range(k + 1, n):
            if len(tuples[j]) <= eff_level:
                end_page = max(start_pages[k], start_pages[j] - 1)
                break

        start_page = max(1, min(start_pages[k], page_count))
        end_page = max(start_page, min(end_page, page_count))

        human = _human_number(tup)
        sections.append(
            {
                "toc_number": number,
                "parent_number": parent_number,
                "level": eff_level,
                "title": titles[k],
                "display_title": f"{human} {titles[k]}".strip(),
                "slug": slugify(titles[k], slug_max_len),
                "is_leaf": is_leaf,
                "start_page": start_page,
                "end_page": end_page,
            }
        )
    return sections


def leaf_sequence(sections: List[dict]) -> List[dict]:
    """Leaves in reading order; drives prev/next chaining (contract section 3)."""
    return [s for s in sections if s["is_leaf"]]


def children_of(sections: List[dict], parent_number: Optional[str]) -> List[dict]:
    """Direct children of a node (or top-level nodes when parent_number is None)."""
    return [s for s in sections if s["parent_number"] == parent_number]


def branch_preamble_range(
    node: dict, sections: List[dict]
) -> Optional[Tuple[int, int]]:
    """Page range ``[start, first_child_start - 1]`` a branch owns before its
    first child -- the "preamble" body that the leaf/branch split would
    otherwise drop (e.g. a chapter intro + content above its one bookmarked
    subsection). Pure; safe to unit-test without PyMuPDF.

    Returns ``None`` when ``node`` is a leaf, has no children, or a child begins
    on the branch's own start page (no preamble exists). When non-None the range
    never overlaps any child's pages, so the extractor can slice it exactly as it
    slices a leaf without double-capturing.
    """
    if node.get("is_leaf"):
        return None
    starts = [
        s["start_page"]
        for s in sections
        if s["parent_number"] == node["toc_number"]
    ]
    if not starts:
        return None
    lo, hi = node["start_page"], min(starts) - 1
    return (lo, hi) if hi >= lo else None
