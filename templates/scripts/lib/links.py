"""Wikilink rendering, extraction, and the library-index managed region.

Vault-contract.md sections 4 (link style) and 6 (managed region).
"""

from __future__ import annotations

import re
from typing import List, Tuple

AUTO_START = "<!-- p2v:auto-start -->"
AUTO_END = "<!-- p2v:auto-end -->"

# Internal wikilinks: [[target]] or [[target|alias]]. Captures target + alias.
_WIKILINK = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]*))?\]\]")


def wikilink(target: str, alias: str) -> str:
    """Vault-relative, aliased wikilink (the only permitted internal link form)."""
    return f"[[{target}|{alias}]]"


def extract_links(text: str) -> List[Tuple[str, str]]:
    """Return (target, alias) pairs for every wikilink in `text`.

    Inside a markdown table the pipe in ``[[target|alias]]`` must be escaped as
    ``\\|`` so it isn't read as a column separator. The capture then keeps that
    trailing backslash on ``target``; strip it so the target resolves.
    """
    out = []
    for m in _WIKILINK.finditer(text):
        target = m.group(1).strip()
        if target.endswith("\\"):
            target = target[:-1].rstrip()
        out.append((target, (m.group(2) or "").strip()))
    return out


def is_bare(target: str) -> bool:
    """A link target is 'bare' (forbidden) if it has no '/' path component."""
    return "/" not in target


def render_managed_block(entries: List[Tuple[str, str]]) -> str:
    """Build the auto-managed bullet list (sorted by target for determinism)."""
    bullets = [f"- {wikilink(t, a)}" for t, a in sorted(entries, key=lambda e: e[0])]
    body = "\n".join(bullets) if bullets else ""
    return f"{AUTO_START}\n{body}\n{AUTO_END}" if body else f"{AUTO_START}\n{AUTO_END}"


def upsert_managed_region(existing_text: str, block: str) -> str:
    """Replace the managed region in `existing_text`, preserving everything else.

    If no region exists yet, append it (with a separating blank line).
    """
    if AUTO_START in existing_text and AUTO_END in existing_text:
        pattern = re.compile(
            re.escape(AUTO_START) + r".*?" + re.escape(AUTO_END), re.DOTALL
        )
        return pattern.sub(lambda _m: block, existing_text, count=1)
    base = existing_text.rstrip("\n")
    return f"{base}\n\n{block}\n" if base else f"{block}\n"
