"""Deterministic YAML frontmatter writer + tolerant reader.

Writing is hand-rolled so key order and quoting are stable across runs and
Python versions (vault-contract.md, section 3). Reading uses PyYAML so we can
parse arbitrary user-touched files in the harness.
"""

from __future__ import annotations

from typing import Optional, Tuple

import yaml

# Canonical key order from the contract. Keys absent from `meta` are omitted.
# `summary` is an optional inferred key written only by the enrichment skill
# (enriched tier); it sits after `tags` and is quoted like any string value.
KEY_ORDER = [
    "title",
    "source",
    "source_pages",
    "boundary",
    "toc_level",
    "toc_number",
    "parent",
    "prev",
    "next",
    "tags",
    "summary",
    "created",
    "generated_by",
]

_QUOTED_KEYS = {"title", "source", "toc_number", "parent", "prev", "next"}
_BARE_KEYS = {"boundary", "generated_by", "created"}


def _quote(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_value(key: str, value) -> str:
    if key == "source_pages":
        start, end = value
        return f"[{int(start)}, {int(end)}]"
    if key == "toc_level":
        return str(int(value))
    if key == "tags":
        return "[" + ", ".join(str(t) for t in value) + "]"
    if key in _QUOTED_KEYS:
        return _quote(value)
    if key in _BARE_KEYS:
        return str(value)
    return _quote(value)


def render(meta: dict) -> str:
    """Render a frontmatter block (including the surrounding ``---`` fences)."""
    lines = ["---"]
    for key in KEY_ORDER:
        if key not in meta or meta[key] is None:
            continue
        lines.append(f"{key}: {_render_value(key, meta[key])}")
    lines.append("---")
    return "\n".join(lines)


def render_note(meta: dict, body: str) -> str:
    """Full note text: frontmatter + blank line + body + trailing newline."""
    body = body.rstrip("\n")
    return f"{render(meta)}\n\n{body}\n"


def split(text: str) -> Tuple[Optional[dict], str]:
    """Return (frontmatter_dict_or_None, body). Tolerant of missing frontmatter."""
    if not text.startswith("---"):
        return None, text
    parts = text.split("\n")
    if parts[0].strip() != "---":
        return None, text
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            fm_text = "\n".join(parts[1:i])
            body = "\n".join(parts[i + 1 :]).lstrip("\n")
            try:
                meta = yaml.safe_load(fm_text) or {}
            except yaml.YAMLError:
                meta = None
            return meta, body
    return None, text
