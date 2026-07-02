---
name: p2v-start-project
description: Setup wizard for a new pdf-to-vault project. Choose the vault output folder, scaffold the Python pipeline + config from templates, install dependencies, and optionally create the default vault map. Trigger with /p2v-start-project.
disable-model-invocation: true
---

# /p2v-start-project

Guided setup. Use the AskQuestion tool for each choice so the user gets clickable
options. Write the pipeline into the **sibling output project**, never into the
kit.

## Steps

1. **Detect the vault.** Walk up from the workspace for the nearest `.obsidian/`
   directory. If found, the default output is `<vaultRoot>/PDF Imports/`;
   otherwise default to `../pdf-vault-output`.

2. **Default folder (AskQuestion).** Offer:
   - "Use default: `<computed default>`" (recommended)
   - "Other" (let the user type a path)
   Record the chosen path as `vault_output` in `pipeline.config.json`.

3. **Split depth (AskQuestion).** Offer: full ToC depth (default, `0`), or split
   only down to level 1 / level 2. Record `split_depth`.

4. **Scaffold the pipeline.** Copy from the kit's `templates/` into the output
   project root (a folder next to the vault, e.g. the vault repo or a `tools/`
   dir the user picks):
   - `scripts/` (extract.py, build_vault.py, verify_vault.py, lib/)
   - `requirements.txt`, `pipeline.config.json`, `verify.config.json`,
     `_templates/`, `.env.example`
   Do not copy into the kit directory.

5. **Install dependencies.** Choose one option:
   - **Python (venv):** In the output project, create a venv and
     `pip install -r requirements.txt`. Confirm `python -c "import fitz,
     pymupdf4llm, yaml"` succeeds. If a pinned wheel is unavailable for the user's
     Python, install the latest and update the pins (note the change).
   - **Docker (no Python needed):** From the kit folder, build the image once:
     `docker build -t p2v .` — then use `docker-run.sh` for every command.
     Vault output paths in `pipeline.config.json` must stay inside the project
     folder (use `./pdf-vault-output`, not `../pdf-vault-output`).
     See `docs/docker.md` for the full walkthrough.

6. **Create default map (AskQuestion).** Offer to scaffold the empty vault
   skeleton now:
   - Create the vault output folder.
   - Write the vault-root `index.md` with a `# Imported PDFs` heading and an empty
     managed region (`<!-- p2v:auto-start -->` / `<!-- p2v:auto-end -->`).
   - Create `_templates/` (note + MOC) and an `assets/` placeholder, and the
     `.p2v/` manifest dir alongside the vault.
   This gives a browsable vault from minute one; later builds register each PDF
   into the managed region.

7. **Report.** Summarize the chosen path, config, and what to run next
   (`/p2v-build-document`). Mention the optional **"Custom File Explorer
   sorting"** (`obsidian-custom-sort`) community plugin: builds scaffold a
   `sortspec.md` (see `docs/vault-contract.md` 1.2) that makes the File Explorer
   show notes in reading order (files and folders interleaved by numeric prefix)
   instead of Obsidian's default folders-before-files. It is view-only and only
   takes effect once the plugin is installed; disable via `sortspec: false`.

## Guardrails

- Confirm the vault path before writing anything.
- Never scaffold into the kit directory.
- Keep `pipeline.config.json` the single place the output path lives.
