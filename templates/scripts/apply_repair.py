#!/usr/bin/env python3
"""Apply a guard-gated table/index repair to a generated note, safely.

The `/p2v-repair-document` skill reformats a malformed table or a glued index in
an already-generated note. Body edits must be provably *layout-only* -- never a
content change (fabrication) and never a touch to a note the kit does not own.
This CLI is the enforced writer that makes both true by construction, so the
agent can never apply a drifting edit by hand:

- Safe-write: refuses any note without `generated_by: p2v`.
- Guard-clean: runs the matching deterministic guard on OLD vs NEW body --
  `lib.table_guard.data_drift_strict` (default) or `lib.index_guard.data_drift`
  (`--kind index`) -- and writes only on a clean result.
- Whole-note layout-only (`--kind table`): the table guard inspects only table
  regions, so prose OUTSIDE tables would otherwise be unguarded. This writer
  additionally asserts every non-table line is byte-identical old-vs-new; only
  table blocks may change. (`--kind index` needs no such check: `index_guard`
  already tokenizes the entire body minus headings.)

Frontmatter is preserved verbatim (re-rendered via `lib.frontmatter`), so the
repair touches the body only.

Usage:
    python apply_repair.py NOTE.md --new-body NEWBODY.md [--kind table|index]
    # NEWBODY may also be piped on stdin (omit --new-body)

Exit 0 = applied (safe); 1 = refused (not owned) / drift / I/O error.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import frontmatter, index_guard, table_guard  # noqa: E402
from lib.text import promote_demoted_label_row  # noqa: E402

GENERATED_BY = "p2v"


def _non_table_lines(md: str) -> list:
    """Body lines that are NOT table rows, in order (fenced-code aware).

    Mirrors `table_guard._iter_table_blocks`'s table detection: outside a fenced
    code block, a line whose first non-space char is ``|`` is a table row. Fence
    lines, prose, headings, and blanks are all kept. Comparing this list old-vs-
    new proves a table repair changed nothing outside the table blocks."""
    out = []
    in_code = False
    for line in md.split("\n"):
        s = line.lstrip()
        if s.startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if not in_code and s.startswith("|"):
            continue
        out.append(line)
    return out


def check(old_body: str, new_body: str, kind: str) -> list:
    """Return a list of human-readable drift messages (empty == safe to apply)."""
    if kind == "index":
        return index_guard.data_drift(old_body, new_body)
    messages = list(table_guard.data_drift_strict(old_body, new_body))
    # Trailing newlines are cosmetic (render_note normalizes them on write), so
    # compare non-table lines after stripping them -- otherwise a stored body's
    # normalized trailing "\n" would read as a spurious prose change.
    old_stripped = old_body.rstrip("\n")
    new_stripped = new_body.rstrip("\n")
    promoted = promote_demoted_label_row(old_stripped)
    if promoted != new_stripped:
        if _non_table_lines(old_stripped) != _non_table_lines(new_stripped):
            messages.append(
                "non-table content changed: a repair may only edit table blocks, "
                "but text/prose outside a table differs (possible fabrication)"
            )
    return messages


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("note")
    ap.add_argument("--kind", choices=("table", "index"), default="table")
    ap.add_argument(
        "--new-body",
        default=None,
        help="file with the proposed new body; if omitted, read from stdin",
    )
    ap.add_argument(
        "--transform",
        choices=("demoted-label-row",),
        default=None,
        help="run a built-in layout-only transform instead of --new-body",
    )
    args = ap.parse_args()

    try:
        with open(args.note, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"apply_repair: cannot read {args.note}: {exc}", file=sys.stderr)
        return 1

    meta, old_body = frontmatter.split(text)
    if not (meta and meta.get("generated_by") == GENERATED_BY):
        print(
            f"apply_repair: refusing non-p2v note (no 'generated_by: p2v'): {args.note}",
            file=sys.stderr,
        )
        return 1

    try:
        if args.transform == "demoted-label-row":
            new_body = promote_demoted_label_row(old_body)
        elif args.new_body is not None:
            with open(args.new_body, encoding="utf-8") as fh:
                new_body = fh.read()
        else:
            new_body = sys.stdin.read()
    except OSError as exc:
        print(f"apply_repair: cannot read new body: {exc}", file=sys.stderr)
        return 1

    drift = check(old_body, new_body, args.kind)
    if drift:
        print(f"apply_repair: DATA DRIFT ({args.kind}) -- NOT applied:")
        for msg in drift:
            print(f"  {msg}")
        return 1

    with open(args.note, "w", encoding="utf-8") as fh:
        fh.write(frontmatter.render_note(meta, new_body))
    print(f"apply_repair: applied {args.kind} repair -> {args.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
