#!/usr/bin/env python3
"""Apply enrichment (summary + topic tags) to a generated note, deterministically.

The enrichment skill is agent-driven, but frontmatter must never be hand-emitted
-- it would drift from the contract's key order/quoting (see
`.cursor/rules/pdf-to-vault-frontmatter-and-links.mdc`). This CLI is the machine
writer: it reads a note with `lib.frontmatter`, sets `summary` and appends tags,
and re-renders via `lib.frontmatter.render_note`, so key order and quoting stay
canonical.

Discipline enforced here:
- Safe-write: refuses any note that is not `generated_by: p2v`.
- Additive tags: never removes or reorders existing tags; `pdf-import` and the
  source slug stay first (they are already first and are never dropped).
- Idempotent: skips a note that already has a `summary` unless `--force`.

Usage:
    python apply_enrichment.py NOTE.md [--summary "..."] [--add-tags a,b] [--force]

Exit 0 = applied (or skipped as already-enriched); 1 = refused / I/O error.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import frontmatter  # noqa: E402

GENERATED_BY = "p2v"


def _clean_summary(text: str) -> str:
    """Collapse whitespace to a single line (summaries are one-line scalars)."""
    return re.sub(r"\s+", " ", text).strip()


def apply(meta: dict, summary: str | None, add_tags: list, force: bool):
    """Mutate and return ``meta`` (or ``None`` when skipped) plus a message.

    Pure w.r.t. I/O; the CLA in ``main`` handles reading/writing and the
    safe-write ``generated_by`` check."""
    if summary is not None and meta.get("summary") and not force:
        return None, "already enriched (has summary); use --force to overwrite"
    if summary is not None:
        meta["summary"] = _clean_summary(summary)
    if add_tags:
        tags = list(meta.get("tags") or [])
        for t in add_tags:
            if t and t not in tags:
                tags.append(t)
        meta["tags"] = tags
    return meta, "applied"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("note")
    ap.add_argument("--summary", default=None, help="faithful one-line condensation")
    ap.add_argument("--add-tags", default="", help="comma-separated tags to append (e.g. topic/melee,enriched)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing summary")
    args = ap.parse_args()

    try:
        with open(args.note, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"apply_enrichment: cannot read {args.note}: {exc}", file=sys.stderr)
        return 1

    meta, body = frontmatter.split(text)
    if not (meta and meta.get("generated_by") == GENERATED_BY):
        print(
            f"apply_enrichment: refusing non-p2v note (no 'generated_by: p2v'): {args.note}",
            file=sys.stderr,
        )
        return 1

    add_tags = [t.strip() for t in args.add_tags.split(",") if t.strip()]
    if args.summary is None and not add_tags:
        print("apply_enrichment: nothing to do (pass --summary and/or --add-tags)")
        return 0

    updated, msg = apply(meta, args.summary, add_tags, args.force)
    if updated is None:
        print(f"apply_enrichment: skipped {args.note}: {msg}")
        return 0

    with open(args.note, "w", encoding="utf-8") as fh:
        fh.write(frontmatter.render_note(updated, body))
    print(f"apply_enrichment: {msg} -> {args.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
