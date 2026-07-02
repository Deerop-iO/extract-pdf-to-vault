#!/usr/bin/env python3
"""Guarded-hand-edit checker: diff two markdown files for table DATA drift.

The deterministic structural normalizers (collapse_table_headers, split_am_traits,
merge_wrapped_table_rows, merge_wrapped_name_rows) clean most weapon charts, but a
few gnarly tables still need a manual reformat. Because the pipeline runs inside an
agent, that hand-edit can be made *provably safe*: reformat the table, then run this
checker. It reuses ``lib.table_guard.data_drift`` -- the same invariant the
extraction guard enforces -- so an accepted hand-edit can only have moved layout,
never added/dropped/changed a data token.

Usage:
    python verify_table.py BEFORE.md AFTER.md [--strict]

``--strict`` selects ``data_drift_strict``, which keeps the multiset invariant
AND additionally rejects a data-row REORDERING (a row swap). Use it for
agent/hand beautify and structural-repair edits (e.g. the `/p2v-repair-document`
skill, which applies through `apply_repair.py`). Without it, the default multiset
invariant matches what the pipeline normalizers use.

Exit 0 = no data drift (safe to apply); 1 = drift (prints the offending tokens);
2 = usage / I/O error.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import table_guard  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("before", help="markdown file BEFORE the hand-edit")
    ap.add_argument("after", help="markdown file AFTER the hand-edit")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="also reject a data-row REORDERING (row swap) on top of the multiset "
        "invariant; use for agent/hand beautify + structural repair edits",
    )
    args = ap.parse_args()

    try:
        with open(args.before, encoding="utf-8") as fh:
            before = fh.read()
        with open(args.after, encoding="utf-8") as fh:
            after = fh.read()
    except OSError as exc:
        print(f"verify_table: cannot read input: {exc}", file=sys.stderr)
        return 2

    check = table_guard.data_drift_strict if args.strict else table_guard.data_drift
    drift = check(before, after)
    if drift:
        print("verify_table: DATA DRIFT -- do NOT apply this edit:")
        for msg in drift:
            print(f"  {msg}")
        return 1
    print("verify_table: clean -- no table data drift; safe to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
