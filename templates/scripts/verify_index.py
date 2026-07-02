#!/usr/bin/env python3
"""Guarded index-edit checker: diff two markdown files for index DATA drift.

Mirrors ``verify_table.py`` for back-of-book index notes. Reuses
``lib.index_guard.data_drift`` -- the ordered entry-token invariant -- so an
accepted reformat can only have de-glued / cleaned layout, never reordered,
added, or dropped a term word or page number. (A true A-Z re-sort is out of
scope and belongs to the deterministic geometry-based ``reconstruct_index``; see
``lib/index_guard.py``.)

Usage:
    python verify_index.py BEFORE.md AFTER.md

Exit 0 = no data drift (safe to apply); 1 = drift (prints the offending tokens);
2 = usage / I/O error.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import index_guard  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("before", help="markdown file BEFORE the reformat")
    ap.add_argument("after", help="markdown file AFTER the reformat")
    args = ap.parse_args()

    try:
        with open(args.before, encoding="utf-8") as fh:
            before = fh.read()
        with open(args.after, encoding="utf-8") as fh:
            after = fh.read()
    except OSError as exc:
        print(f"verify_index: cannot read input: {exc}", file=sys.stderr)
        return 2

    drift = index_guard.data_drift(before, after)
    if drift:
        print("verify_index: DATA DRIFT -- do NOT apply this edit:")
        for msg in drift:
            print(f"  {msg}")
        return 1
    print("verify_index: clean -- no index data drift; safe to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
