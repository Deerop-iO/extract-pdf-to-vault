# pdf-to-vault agent kit

**Repository:** https://github.com/Deerop-iO/extract-pdf-to-vault · **Latest release:** `v1.0.1`

An agent kit for **Cursor** and **Claude Code** that deterministically extracts
PDFs into a structured Obsidian markdown vault. Modeled on the `figma-to-code`
kit: always-on rules, a router skill, explicit slash-command workflows, a
copy-out template pipeline, and a consistency-verification harness.

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

- `AGENTS.md` / `CLAUDE.md` — the agent charter. Auto-loaded by Codex and Claude Code respectively; paste `AGENTS.md` into Cursor chat to brief the agent.
- `.cursor/rules/` — always-on discipline (7 `.mdc` files).
- `.cursor/skills/pdf-to-vault-agent/` — router `SKILL.md`, `references/`, and
  `workflows/` (the `/p2v-*` slash commands for Cursor).
- `.claude/commands/` — `/p2v-*` slash commands for Claude Code (mirror of the Cursor workflows).
- `docs/` — human-facing specs. **`vault-contract.md` is the single source of
  truth** for structure and naming.
- `DOCKER.md` — Docker installation and usage guide (no Python required).
- `Dockerfile` / `docker-entrypoint.sh` / `docker-run.sh` / `.dockerignore` — Docker support.
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

When using **Docker**, set `vault_output` to a path inside your project folder
(e.g. `./pdf-vault-output`), not `../…` — see [`DOCKER.md`](DOCKER.md).

## Quick start

1. Run `/p2v-start-project` to choose a vault path, scaffold the pipeline, and
   optionally create the default vault map.
2. Run `/p2v-build-document` and point it at a PDF.
3. Run `/p2v-verify-vault` to confirm consistency.

Optional post-build (same slash commands in Cursor and Claude Code):

- `/p2v-enrich-document` — add faithful summaries and controlled topic tags
  (`enriched` tier).
- `/p2v-repair-document` — guard-gated table/index layout repair (tier-neutral).

## Requirements

**Option A — Python:** Python 3.10+ and `pip install -r templates/requirements.txt`
(PyMuPDF, pymupdf4llm, PyYAML). No network access or secrets needed.

**Option B — Docker (no Python install needed):** Docker Desktop installed and
running. Build the image once from the kit folder: `docker build -t p2v .` —
then use `docker-run.sh` for every pipeline command. See [`DOCKER.md`](DOCKER.md)
for the full installation and usage guide.

## Status

The core pipeline (extract → build → verify) is stable. Post-build **enrich** and
**repair** skills ship today; Docker support is in `v1.0.1`. Remaining work —
OCR for scanned PDFs, heading-refined boundaries, refresh/orchestrator workflows
— is tracked in `BACKLOG.md` (see `DEFERRED.md` for the high-level defer list).
