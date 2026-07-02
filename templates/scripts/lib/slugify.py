"""Deterministic slug generation (vault-contract.md, section 2.3)."""

from __future__ import annotations

import re
import unicodedata

DEFAULT_MAX_LEN = 60
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(title: str, max_len: int = DEFAULT_MAX_LEN) -> str:
    """Pure function: title -> URL/file-safe slug.

    Steps (must match the contract exactly):
      1. NFKD normalize + drop combining marks (ASCII-fold).
      2. Lowercase.
      3. Collapse any run of non [a-z0-9] into a single '-'.
      4. Strip leading/trailing '-'.
      5. Truncate to max_len, strip a trailing '-'.
      6. Empty -> 'section'.
    """
    if title is None:
        title = ""
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    dashed = _NON_SLUG.sub("-", lowered).strip("-")
    if max_len and len(dashed) > max_len:
        dashed = dashed[:max_len].rstrip("-")
    return dashed or "section"
