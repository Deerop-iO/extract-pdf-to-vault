#!/usr/bin/env python3
"""Consistency harness for a generated vault (vault-contract.md, section 7).

Gates (each toggleable via verify.config.json):
  frontmatter  - required keys present, correct shapes
  filenames    - naming contract (numbered leaves / folder notes / one index.md)
  links        - every internal wikilink is aliased, non-bare, and resolves
  assets       - every referenced image exists on disk
  reachability - every generated note is reachable from the library index
  tables       - markdown tables have consistent columns, no junk/page-number rows
  boilerplate  - no configured boilerplate (e.g. a DRM line) survived into a note
  heading_artifacts - no spaced-out heading survived (e.g. "## C H A P T E R")

Exit code 0 = all enabled gates pass; 1 = at least one failure.

Usage:
    python verify_vault.py --vault <vault-output> [--config verify.config.json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import frontmatter, links, naming  # noqa: E402
from lib.text import collapse_spaced_caps  # noqa: E402

GENERATED_BY = "p2v"
_NUMBERED = re.compile(r"^\d{2,}(\.\d{2,})*-[a-z0-9][a-z0-9-]*$")
_SLUG_CHARS = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
_IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_SEP_CELL = re.compile(r"^:?-{2,}:?$")
REQUIRED_KEYS = ["title", "source", "source_pages", "toc_level", "toc_number", "tags", "created", "generated_by"]
DEFAULT_GATES = {
    "frontmatter": True,
    "filenames": True,
    "links": True,
    "assets": True,
    "reachability": True,
    "tables": True,
    "boilerplate": True,
    "heading_artifacts": True,
}


def _load_cfg(path: str | None) -> tuple[dict, list]:
    """Return (gates, boilerplate_patterns) merged with defaults."""
    gates = dict(DEFAULT_GATES)
    patterns: list = []
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        gates.update(raw.get("gates", {}))
        patterns = list(raw.get("boilerplate_patterns", []))
    return gates, patterns


# Directories that hold scaffolding/config, not vault notes.
_IGNORED_DIRS = {"_templates", ".p2v", ".obsidian", ".trash", ".git"}


def _all_md(vault: str) -> list:
    out = []
    for root, dirs, files in os.walk(vault):
        # Prune ignored and dot/underscore-prefixed directories in place.
        dirs[:] = [
            d for d in dirs if d not in _IGNORED_DIRS and not d.startswith(".")
        ]
        for f in files:
            if f.endswith(".md"):
                abs_p = os.path.join(root, f)
                out.append(os.path.relpath(abs_p, vault).replace(os.sep, "/"))
    return sorted(out)


def _read(vault: str, rel: str) -> str:
    with open(os.path.join(vault, rel), encoding="utf-8") as fh:
        return fh.read()


def check_frontmatter(vault, md_files, failures):
    for rel in md_files:
        if rel == naming.LIBRARY_INDEX:
            continue
        meta, _ = frontmatter.split(_read(vault, rel))
        if not meta:
            failures.append(f"[frontmatter] {rel}: missing or unparseable frontmatter")
            continue
        if meta.get("generated_by") != GENERATED_BY:
            continue  # user-authored, not our concern
        for key in REQUIRED_KEYS:
            if key not in meta:
                failures.append(f"[frontmatter] {rel}: missing key '{key}'")
        sp = meta.get("source_pages")
        if not (isinstance(sp, list) and len(sp) == 2 and all(isinstance(x, int) for x in sp)):
            failures.append(f"[frontmatter] {rel}: source_pages must be [int, int]")
        if not isinstance(meta.get("tags"), list) or "pdf-import" not in (meta.get("tags") or []):
            failures.append(f"[frontmatter] {rel}: tags must be a list containing 'pdf-import'")
        # `summary` is an optional inferred key (enrichment skill). No new
        # required key; just assert its shape when present.
        if "summary" in meta and not isinstance(meta.get("summary"), str):
            failures.append(f"[frontmatter] {rel}: summary, if present, must be a string")


def check_filenames(vault, md_files, failures):
    for rel in md_files:
        if rel == naming.LIBRARY_INDEX:
            continue
        # The naming contract governs generated notes only. User-authored notes
        # (e.g. a `sortspec` Custom-Sort spec) are the user's business; skip them,
        # mirroring the frontmatter gate.
        meta, _ = frontmatter.split(_read(vault, rel))
        if not (meta and meta.get("generated_by") == GENERATED_BY):
            continue
        directory, fname = os.path.split(rel)
        stem = fname[:-3]
        dir_base = os.path.basename(directory)
        if stem == dir_base:
            ok = True  # folder note (branch MOC or per-PDF MOC)
        elif _NUMBERED.match(stem):
            ok = True
        else:
            ok = False
        if not ok or not _SLUG_CHARS.match(stem):
            failures.append(f"[filenames] {rel}: does not match the naming contract")


def _is_index_target(target: str) -> bool:
    """The library-index link: either the bare ``index`` (standalone vault) or
    an Obsidian-root-relative ``.../index`` (vault inside a larger Obsidian
    vault). The on-disk file is always LIBRARY_INDEX at the vault root."""
    return target == "index" or target.endswith("/index")


def check_links(vault, md_files, failures):
    existing = set(md_files)
    for rel in md_files:
        haystack = _read(vault, rel)
        for target, alias in links.extract_links(haystack):
            target = target.split("#", 1)[0]  # drop any heading anchor
            if _is_index_target(target):  # the one permitted cross-cutting link
                if naming.LIBRARY_INDEX not in existing:
                    failures.append(f"[links] {rel}: links to missing library index")
                continue
            if links.is_bare(target):
                failures.append(f"[links] {rel}: bare wikilink '[[{target}]]' (must be vault-relative)")
                continue
            if not alias:
                failures.append(f"[links] {rel}: wikilink to '{target}' has no alias")
            if f"{target}.md" not in existing:
                failures.append(f"[links] {rel}: unresolved wikilink target '{target}'")


def check_assets(vault, md_files, failures):
    for rel in md_files:
        directory = os.path.dirname(rel)
        body = _read(vault, rel)
        for m in _IMG.finditer(body):
            ref = m.group(1)
            if ref.startswith("http://") or ref.startswith("https://") or ref.startswith("ASSET:"):
                failures.append(f"[assets] {rel}: unresolved/transient image ref '{ref}'")
                continue
            abs_asset = os.path.normpath(os.path.join(vault, directory, ref))
            if not os.path.exists(abs_asset):
                failures.append(f"[assets] {rel}: missing asset '{ref}'")


def check_reachability(vault, md_files, failures):
    existing = set(md_files)
    if naming.LIBRARY_INDEX not in existing:
        failures.append("[reachability] no library index.md at vault root")
        return
    reachable = set()
    queue = [naming.LIBRARY_INDEX]
    while queue:
        rel = queue.pop()
        if rel in reachable or rel not in existing:
            continue
        reachable.add(rel)
        for target, _alias in links.extract_links(_read(vault, rel)):
            target = target.split("#", 1)[0]  # drop any heading anchor
            tgt = naming.LIBRARY_INDEX if _is_index_target(target) else f"{target}.md"
            if tgt in existing and tgt not in reachable:
                queue.append(tgt)
    generated = {
        rel for rel in md_files
        if rel == naming.LIBRARY_INDEX
        or (frontmatter.split(_read(vault, rel))[0] or {}).get("generated_by") == GENERATED_BY
    }
    for rel in sorted(generated - reachable):
        failures.append(f"[reachability] {rel}: not reachable from the library index")


def _row_cells(row: str) -> list:
    """Split a markdown table row into trimmed cells (drop the outer pipes)."""
    r = row.strip()
    if r.startswith("|"):
        r = r[1:]
    if r.endswith("|"):
        r = r[:-1]
    return [c.strip() for c in r.split("|")]


def _is_separator(cells: list) -> bool:
    non_empty = [c for c in cells if c]
    return bool(non_empty) and all(_SEP_CELL.match(c) for c in non_empty)


def _iter_table_blocks(lines: list):
    """Yield runs of consecutive table rows as [(lineno, cells), ...], skipping
    fenced code blocks (where a leading '|' is not a table)."""
    block: list = []
    in_code = False
    for i, line in enumerate(lines, 1):
        s = line.lstrip()
        if s.startswith("```"):
            in_code = not in_code
            if block:
                yield block
                block = []
            continue
        if not in_code and s.startswith("|"):
            block.append((i, _row_cells(line)))
        elif block:
            yield block
            block = []
    if block:
        yield block


def check_tables(vault, md_files, failures):
    """Flag tables whose data rows disagree on column count -- the validated
    junk signal (e.g. a page number leaked into a row as an extra column).

    Deliberately the *only* table check: a single-cell numeric row may be a
    point-total subtotal and an all-empty row may be a blank character-sheet
    form field, so neither is flagged. A subtotal sits in the table's normal
    last column and keeps the column count consistent, so it never trips this.
    A genuinely ragged form table (e.g. a wizard sheet) will trip it; that is a
    real raggedness surfaced for review, and the gate is toggleable.
    """
    for rel in md_files:
        if rel == naming.LIBRARY_INDEX:
            continue
        for block in _iter_table_blocks(_read(vault, rel).split("\n")):
            data_rows = [cells for (_ln, cells) in block if not _is_separator(cells)]
            counts = {len(cells) for cells in data_rows}
            if len(counts) > 1:
                failures.append(
                    f"[tables] {rel}: inconsistent table column counts {sorted(counts)} "
                    f"(table starting line {block[0][0]})"
                )


def check_boilerplate(vault, md_files, failures, patterns):
    compiled = [re.compile(p) for p in patterns]
    if not compiled:
        return  # gate is a no-op until the user configures patterns
    for rel in md_files:
        body = _read(vault, rel)
        for pat in compiled:
            if pat.search(body):
                failures.append(
                    f"[boilerplate] {rel}: configured boilerplate survived "
                    f"(pattern /{pat.pattern}/)"
                )
                break


def check_heading_artifacts(vault, md_files, failures):
    """Flag spaced-out font artifacts that survived into a markdown heading,
    e.g. ``## C H A P T E R  F O U R``. Mirrors the extractor's fix exactly: a
    heading is an artifact iff ``collapse_spaced_caps`` would change it.

    Scoped to heading lines (and skips fenced code) for the same reason the fix
    is -- a single-letter stat-table column run (``M WS BS S T W I A``) is data,
    not a spaced word, and must never be flagged or rewritten.
    """
    for rel in md_files:
        in_code = False
        for i, line in enumerate(_read(vault, rel).split("\n"), start=1):
            if line.lstrip().startswith("```"):
                in_code = not in_code
                continue
            if in_code or not line.lstrip().startswith("#"):
                continue
            if collapse_spaced_caps(line) != line:
                failures.append(
                    f"[heading_artifacts] {rel}: spaced-out heading on line {i}: "
                    f"{line.strip()[:60]!r}"
                )


GATE_FUNCS = {
    "frontmatter": check_frontmatter,
    "filenames": check_filenames,
    "links": check_links,
    "assets": check_assets,
    "reachability": check_reachability,
    "tables": check_tables,
    "boilerplate": check_boilerplate,
    "heading_artifacts": check_heading_artifacts,
}


def verify(vault: str, gates: dict, boilerplate_patterns: list | None = None) -> list:
    md_files = _all_md(vault)
    failures: list = []
    for name, enabled in gates.items():
        if not (enabled and name in GATE_FUNCS):
            continue
        if name == "boilerplate":
            check_boilerplate(vault, md_files, failures, boilerplate_patterns or [])
        else:
            GATE_FUNCS[name](vault, md_files, failures)
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a generated vault.")
    parser.add_argument("--vault", required=True)
    parser.add_argument("--config", default="verify.config.json")
    args = parser.parse_args()

    gates, patterns = _load_cfg(args.config)
    failures = verify(args.vault, gates, patterns)
    enabled = [g for g, on in gates.items() if on]
    if failures:
        print(f"FAIL ({len(failures)} issue(s)); gates: {', '.join(enabled)}")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    print(f"PASS; gates: {', '.join(enabled)}")


if __name__ == "__main__":
    main()
