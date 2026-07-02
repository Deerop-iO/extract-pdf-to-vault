#!/usr/bin/env python3
"""Clean recurring PDF boilerplate out of an already-built vault, in place.

A one-off maintenance tool for vaults that were generated *before* the
extraction pipeline gained boilerplate normalization. It reuses the kit's
``lib.text.normalize_body`` so its behavior matches the live pipeline exactly
(stop deleting table rows on a numeric/empty heuristic; drop only artifact
lines and the furniture residue left where boilerplate was excised).

Design / safety:
  - Body-only: YAML frontmatter bytes are preserved verbatim.
  - ``strip_page_numbers=False``: this tool only removes the configured
    boilerplate (+ its residue), never unrelated standalone page numbers.
  - Idempotent: a second run is a no-op.
  - Dry run by default. ``--apply`` writes; ``--report`` saves a unified-diff
    log; ``--backup-dir`` copies originals before writing.

Patterns live in an external ``--patterns-file`` (one regex per line, ``#``
comments allowed) so a PII-bearing pattern (e.g. a watermark with an email)
never has to be committed into the kit.

Usage:
  python tools/clean_existing_vault.py --vault <dir> --patterns-file <file>
  python tools/clean_existing_vault.py --vault <dir> --patterns-file <file> \
      --report cleanup-report.json --backup-dir cleanup-backup --apply
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import sys

_KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_KIT_ROOT, "templates", "scripts"))
from lib.text import normalize_body  # noqa: E402

# Mirror the verifier's ignored scaffolding/config dirs.
_IGNORED_DIRS = {"_templates", ".p2v", ".obsidian", ".trash", ".git"}
_LIBRARY_INDEX = "index.md"

# For the dry-run review of picture-text blocks: capture the text *between* a
# Start and End "picture text" marker so we can flag any block that carries real
# content (not just the watermark) before its markers are stripped.
_PIC_BLOCK = re.compile(
    r"\*\*-+ *Start of picture text *-+\*\*(.*?)\*\*-+ *End of picture text *-+\*\*",
    re.S,
)
_BR = re.compile(r"<br\s*/?>", re.I)
_WATERMARK_HINT = "This ebook belongs to"


def _load_patterns(path: str) -> list:
    out = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def _iter_notes(vault: str):
    for dirpath, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS and not d.startswith(".")]
        for name in sorted(files):
            if name.endswith(".md") and not (
                os.path.relpath(os.path.join(dirpath, name), vault) == _LIBRARY_INDEX
            ):
                yield os.path.join(dirpath, name)


def _split_frontmatter(text: str) -> tuple:
    """Return (prefix, body) where prefix is the frontmatter block (including
    its closing '---' and the following newline) preserved byte-for-byte, and
    body is everything after. (``""``, text) when there is no frontmatter.

    Splitting and rejoining on ``\\n`` is lossless (trailing newline included),
    so ``prefix + body == text``."""
    if not text.startswith("---"):
        return "", text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return "", text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            prefix = "\n".join(lines[: i + 1]) + "\n"
            body = "\n".join(lines[i + 1:])
            return prefix, body
    return "", text


def _transform(text: str, patterns: list) -> str:
    prefix, body = _split_frontmatter(text)
    new_body = normalize_body(body, boilerplate_patterns=patterns, strip_page_numbers=False)
    return (prefix + new_body).rstrip("\n") + "\n"


def _flag_picture_blocks(rel: str, body: str, patterns: list, flagged: list) -> None:
    """Record any picture-text block whose inner content is more than just the
    watermark / line breaks, so the operator can review what stays inline once
    the markers are stripped."""
    compiled = [re.compile(p) for p in patterns]
    for inner in _PIC_BLOCK.findall(body):
        residue = inner
        for pat in compiled:
            residue = pat.sub("", residue)
        residue = _BR.sub(" ", residue)
        if _WATERMARK_HINT in residue:
            residue = ""  # watermark handled by its own pattern; ignore here
        if residue.strip():
            flagged.append((rel, " ".join(residue.split())[:120]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", required=True, help="Vault folder to clean (walked recursively).")
    ap.add_argument("--patterns-file", required=True, help="Regex list, one per line; '#' comments allowed.")
    ap.add_argument("--report", help="Write a JSON unified-diff log of all changes to this path.")
    ap.add_argument("--backup-dir", help="Copy each original (preserving relative path) here before writing.")
    ap.add_argument("--apply", action="store_true", help="Write changes (default is a dry run).")
    args = ap.parse_args()

    if not os.path.isdir(args.vault):
        ap.error(f"--vault not found: {args.vault}")
    patterns = _load_patterns(args.patterns_file)
    if not patterns:
        ap.error(f"no patterns in {args.patterns_file}")

    changes = []  # (rel, original, new)
    flagged: list = []  # (rel, residue snippet) -- picture-text blocks with real content
    scanned = 0
    for path in _iter_notes(args.vault):
        rel = os.path.relpath(path, args.vault)
        scanned += 1
        with open(path, encoding="utf-8") as fh:
            original = fh.read()
        _flag_picture_blocks(rel, original, patterns, flagged)
        new = _transform(original, patterns)
        if new != original:
            changes.append((rel, original, new))

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] vault={args.vault}")
    print(f"  scanned: {scanned} notes")
    print(f"  changed: {len(changes)} notes")
    for rel, _o, _n in changes:
        print(f"     - {rel}")
    if flagged:
        print(f"  picture-text blocks with non-watermark content (review): {len(flagged)}")
        for rel, snippet in flagged:
            print(f"     ! {rel}: {snippet}")

    if changes:
        rel0, o0, n0 = changes[0]
        sample = list(difflib.unified_diff(
            o0.splitlines(), n0.splitlines(), fromfile=f"a/{rel0}", tofile=f"b/{rel0}", lineterm=""
        ))
        print(f"\n  --- sample diff: {rel0} ---")
        print("\n".join("    " + ln for ln in sample[:40]))

    if args.report:
        report = [
            {
                "file": rel,
                "diff": list(difflib.unified_diff(
                    o.splitlines(), n.splitlines(), fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""
                )),
            }
            for rel, o, n in changes
        ]
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        print(f"\n  report -> {args.report}")

    if args.apply:
        for rel, original, new in changes:
            if args.backup_dir:
                dst = os.path.join(args.backup_dir, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "w", encoding="utf-8") as fh:
                    fh.write(original)
            with open(os.path.join(args.vault, rel), "w", encoding="utf-8") as fh:
                fh.write(new)
        print(f"\n  wrote {len(changes)} files"
              + (f"; backups -> {args.backup_dir}" if args.backup_dir else ""))
    else:
        print("\n  (dry run -- no files written; pass --apply to write)")


if __name__ == "__main__":
    main()
