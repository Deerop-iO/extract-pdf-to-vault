"""Deterministic index "diff-guard": prove an index reformat changed no data.

Post-build, a back-of-book index note is a list of ``term ... page-numbers``
entries. pymupdf4llm sometimes GLUES several column entries onto one physical
line and strips their structure; an agent may reformat (de-glue) such an index.
This guard makes that edit provably safe.

The enforced invariant is: **the ordered sequence of entry tokens is preserved**
-- every term word and every page number, in reading order, across all
non-heading lines. This:

- permits de-gluing (splitting one physical line into several entry lines) and
  cosmetic cleanup (dropping dotted leaders; adding or removing ``### A``
  letter-group HEADINGS, which are ignored) -- none of these change linear order;
- rejects any reordering, insertion, or deletion of a term word or page number.

In particular a page-number swap between adjacent terms
(``Axe 5, Bow 9`` -> ``Axe 9, Bow 5``) reorders the token stream and IS caught --
the failure mode that a flat term/page multiset would miss.

Consequence (documented, deliberate): a true A-Z RE-SORT of scrambled entries
reorders the stream and will NOT pass this guard. Re-associating pages to terms
cannot be verified from the text alone, so genuine re-ordering belongs to the
deterministic, geometry-based ``reconstruct_index`` (extract time), not an agent
edit. This guard covers order-preserving de-gluing / cleanup only.

Wikilinks collapse to their alias (the printed page number or term), so a
linkified index and its plain-text source tokenize identically. Pure; no I/O.
"""

from __future__ import annotations

import re
from typing import List

_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_TOKEN = re.compile(r"[a-z]+|[0-9]+")


def _strip_frontmatter(md: str) -> str:
    return _FRONTMATTER.sub("", md, count=1)


def _index_token_sequence(md: str) -> List[str]:
    """Ordered word/page tokens across non-heading, non-code index lines.

    Headings (``#`` lines) are ignored so letter-group headers may be freely
    added or removed. Everything is lowercased; tokens are maximal runs of
    letters or of digits, in document order."""
    out: List[str] = []
    in_code = False
    for line in _strip_frontmatter(md).split("\n"):
        s = line.lstrip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or s.startswith("#"):
            continue
        text = _WIKILINK.sub(lambda m: m.group(2) or m.group(1), line)
        out.extend(_TOKEN.findall(text.lower()))
    return out


def data_drift(before: str, after: str) -> List[str]:
    """Return human-readable drift messages (empty == no drift).

    Compares the ordered index token sequences of ``before`` and ``after``."""
    b = _index_token_sequence(before)
    a = _index_token_sequence(after)
    if b == a:
        return []
    j = 0
    for j, (x, y) in enumerate(zip(b, a)):
        if x != y:
            break
    else:
        j = min(len(b), len(a))
    bx = b[j] if j < len(b) else "<end>"
    ax = a[j] if j < len(a) else "<end>"
    return [
        f"index token order changed at position {j}: {bx!r} -> {ax!r} "
        f"(len {len(b)} -> {len(a)})"
    ]
