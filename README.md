# pdf-to-vault agent kit

A Cursor agent kit that deterministically extracts PDFs into a structured
Obsidian markdown vault. Modeled on the `figma-to-code` kit: always-on rules, a
router skill, explicit slash-command workflows, a copy-out template pipeline,
and a consistency-verification harness.

The PDF table of contents drives a nested folder/file structure with stable,
deterministic naming, so the same PDF always produces the same vault.

## Pipeline at a glance

```
PDF --extract.py--> manifest.json --build_vault.py--> Obsidian vault --verify_vault.py--> PASS/FAIL
     (PyMuPDF +                     (notes, MOCs,
      pymupdf4llm)                   assets, links)
```

1. **Extract** (`scripts/extract.py`) — PyMuPDF `get_toc()` + pymupdf4llm
   page-level markdown -> a normalized `manifest.json` (the source of truth) plus
   staged image assets.
2. **Build** (`scripts/build_vault.py`) — manifest -> nested notes with
   frontmatter, folder-note MOCs, vault-relative aliased wikilinks, copied
   assets, and a co-owned library index.
3. **Verify** (`scripts/verify_vault.py`) — gates for frontmatter schema,
   filename convention, link integrity, asset existence, and reachability.

## Repository map

- `AGENTS.md` / `CLAUDE.md` — the agent charter. Auto-loaded by Codex and Claude Code respectively; paste into Cursor chat to brief the agent. `USE_THIS.md` redirects here.
- `.cursor/rules/` — always-on discipline (7 `.mdc` files).
- `.cursor/skills/pdf-to-vault-agent/` — router `SKILL.md`, `references/`, and
  `workflows/` (the `/p2v-*` slash commands for Cursor).
- `.claude/commands/` — `/p2v-*` slash commands for Claude Code (mirror of the Cursor workflows).
- `docs/` — human-facing specs. **`vault-contract.md` is the single source of
  truth** for structure and naming.
- `templates/` — the Python pipeline + config, copied into the sibling vault
  project by `/p2v-start-project`.
- `tests/` — exercises the `lib/` helpers that ship in `templates/scripts/lib/`.
- `tools/` — development and maintenance artifacts (test vault snapshots, verify
  reports, `clean_existing_vault.py`). Not required to run the pipeline; most
  contents are gitignored.

## Kit vs. output

The kit holds *how to extract*. Generated notes go into a **sibling vault output
folder** (default `../pdf-vault-output`, or a subfolder of your real Obsidian
vault). Never write generated notes into this kit directory.

## Quick start

1. Run `/p2v-start-project` to choose a vault path, scaffold the pipeline, and
   optionally create the default vault map.
2. Run `/p2v-build-document` and point it at a PDF.
3. Run `/p2v-verify-vault` to confirm consistency.

## Requirements

Python 3.10+ and the pinned dependencies in `templates/requirements.txt`
(PyMuPDF, pymupdf4llm, PyYAML). Phase 1 needs no network access or secrets.

## Status

Phase 1 (working end-to-end pipeline) is implemented. See `BACKLOG.md` and
`DEFERRED.md` for Phase 2 (enrichment, OCR, more workflows).
