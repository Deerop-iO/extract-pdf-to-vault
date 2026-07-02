---
name: p2v-build-document
description: Convert one PDF into a nested Obsidian vault tree (notes, folder-note MOCs, assets, library index entry) using the deterministic pipeline, then verify it. Trigger with /p2v-build-document.
disable-model-invocation: true
---

# /p2v-build-document

Turn a single PDF into a structured vault subtree. Assumes `/p2v-start-project`
has scaffolded the pipeline; if not, run that first.

## Preconditions

- The output project has `scripts/`, `pipeline.config.json`, and an installed
  venv (PyMuPDF, pymupdf4llm, PyYAML).
- You have a path to the source PDF and a `vault_output` in the config.

## Steps

1. **Scope.** Confirm the PDF path, the vault output path (from
   `pipeline.config.json`), the split depth, and the fidelity tier (`clean` by
   default). State them in a `Scope` section.

2. **Extract.** Run:
   ```
   python scripts/extract.py "<pdf>" --out "<.p2v dir>" --config pipeline.config.json
   ```
   Supported flags (append to the command as needed):
   - `--fallback toc|headings|pages` — hierarchy fallback when no embedded ToC.
   - `--ignore-toc` — discard a degenerate embedded ToC; requires `--fallback`.
   - `--toc-page N` — pin the printed ToC page number for `--fallback toc`.
   - `--write-images` — extract and embed PDF images into the manifest (off by
     default; use for PDFs with meaningful diagrams or UI screenshots).

   If the user's prompt mentions images or diagrams (e.g. "include images",
   "--write-images"), add `--write-images` to the extract command.

   - If it reports "no embedded table of contents," stop and ask the user
     whether to re-run with `--fallback toc` (hierarchy from the printed
     contents page), `--fallback headings` (flat, page-level), or
     `--fallback pages` (one note per page). Never invent a hierarchy.
   - If it reports "looks scanned," stop and surface the OCR-is-opt-in message.
   Then summarize the manifest in an `Extraction` section (ToC source, section
   and leaf counts, warnings). Do not paste raw page text.

3. **Structure.** In a `Structuring` section, state the inferred decisions: split
   depth, how slugs/numbers were derived, and the resulting folder/file plan.
   These come straight from the contract — do not improvise naming.

4. **Build.** Run:
   ```
   python scripts/build_vault.py "<.p2v dir>/<slug>.manifest.json" --vault "<vault_output>"
   ```
   If it refuses to overwrite a user-authored file, stop and report the path —
   do not delete the user's note.

5. **Verify (blocking).** Run:
   ```
   python scripts/verify_vault.py --vault "<vault_output>" --config verify.config.json
   ```
   If any gate fails, fix the cause (usually a contract/pipeline issue) and
   re-run. Do not hand-edit generated notes to pass the gate.

6. **Report.** In `Output`, list the files written (counts + the per-PDF MOC
   path). In `Gotchas`, note the page-level boundary caveat, any fallback used,
   the fidelity tier, and suggest the next step.

## Guardrails

- The manifest is the source of truth; never fabricate sections or content.
- Write only into the sibling vault. Respect the safe-write model.
- Keep `Extracted` / `Inferred` / `Output` visibly separate.
- **Table data guard (extraction-time).** When the gated structural table
  normalizers are on (Necromunda configs), `extract.py` runs
  `lib/table_guard.data_drift` after them and **hard-fails extraction** if any
  table DATA token was added/dropped/changed. If extraction stops with a
  `table_guard:` message, a normalizer is altering data — fix the rule, never
  loosen the guard to get past it.
- **Demoted weapon-chart headers are auto-fixed.** The
  `group-row -> separator -> label-row` shape — markdown header is a near-empty
  spanning row, real labels (`Weapon`/`Grenade` …) land below the separator, so
  Obsidian won't render a table — is repaired by `promote_header_below_separator`
  (on in Necromunda configs, runs first, guard-aware via the shared
  `_is_demoted_header_table` predicate). If a freshly built weapon chart still
  shows a near-empty header row, re-extract with that flag on rather than
  hand-editing.
- **Guarded hand-edit fallback.** For any chart the deterministic rules still
  cannot fully clean, reformat the table *in Cursor*, then prove it is safe before
  applying: copy the current note table to a scratch `before.md`, save your
  reformat as `after.md`, and run `python scripts/verify_table.py before.md
  after.md`. Apply only when it reports clean. Do not hand-edit a generated note
  merely to pass the vault `tables` gate.
