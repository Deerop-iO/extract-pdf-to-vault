---
name: p2v-repair-document
description: Post-build structural repair for a generated vault. Reformats malformed tables and glued index pages in place, with every content edit proven layout-only by a deterministic guard (no data changed, no rows reordered). Cheap by design -- opens only notes with tables/index, never summarizes. Tier-neutral: a repaired note keeps its current fidelity tier. Trigger with /p2v-repair-document.
disable-model-invocation: true
---

# /p2v-repair-document

Fix broken **structure** in already-generated notes for a single source: a table
that renders wrong, or an index whose entries are glued together. Run in chat
AFTER `build_vault.py` + `verify_vault.py`. It never runs the pipeline and adds
no dependency. Read [references/repair.md](../../references/repair.md) first; it
holds the discipline (both guard invariants, detection, limits).

This skill is **tier-neutral**: every edit is proven layout-only, so it changes
no content and does **not** promote a note to `enriched`. A repaired `clean` note
stays `clean`. (For summaries + topic tags, use `/p2v-enrich-document`.)

## Preconditions

- The vault was built (`build_vault.py` has run).
- You know the source slug and `vault_output` (`pipeline.config.json`).

## Steps

1. **Scope.** Confirm the source slug and vault path. Get the owned note list
   from `.p2v/<slug>.generated.json` (or walk `<vault>/<slug>/`). Only ever touch
   notes whose frontmatter has `generated_by: p2v`. State what you will repair.

2. **Detect the worklist.**
   - **Tables:** the actionable list is `verify_vault.py`'s `[tables]` failures --
     run it and read the report. This skill is what you reach for **when the
     tables gate is failing** (or the user points at a specific bad table). On an
     already-passing vault the auto-worklist is empty; a "valid-but-ugly" table is
     only in scope if the **user points at it**.
   - **Index:** index notes are named `<num>-index.md` (an "Index" ToC entry
     slugs to `index`; distinct from the root library `index.md`). Repair them
     **only where `reconstruct_index` is OFF** for this source
     (`pipeline.config.json`). If it is ON, the deterministic geometry rebuild
     owns the index -- **skip**.

3. **Guard-gated repair.** For each candidate, propose a reformat and apply it
   through the enforced writer, which refuses non-owned notes, runs the matching
   guard, and (for tables) also proves nothing outside the table changed:
   - Write your proposed new body to a scratch file (a temp dir, NOT `.p2v/`).
   - Tables:
     ```
     python scripts/apply_repair.py "<note>" --kind table --new-body "<after.md>"
     ```
     For a demoted benefit-table header (`|Selections||| / sep / |Available|…|Cost|`),
     the built-in transform promotes the real header row and emits the group title
     as prose above the table:
     ```
     python scripts/apply_repair.py "<note>" --kind table --transform demoted-label-row
     ```
   - Index:
     ```
     python scripts/apply_repair.py "<note>" --kind index --new-body "<after.md>"
     ```
   - Exit 0 = applied (frontmatter preserved, body replaced). Exit 1 = refused or
     data drift -- **do not** hand-edit around it; flag the note for human review.
     An ugly-but-correct table beats a pretty-but-wrong one.
   - You may reuse the `lib/text.py` transforms as building blocks. Do **not** A-Z
     re-sort an index (the guard rejects re-ordering -- see references/repair.md).
   - For a side-by-side preview before applying, `scripts/verify_table.py
     before.md after.md --strict` / `scripts/verify_index.py before.md after.md`
     run the same guards standalone.

4. **Re-verify.** Run `python scripts/verify_vault.py --vault "<vault>" --config
   verify.config.json`. The `[tables]` gate must now pass; the vault stays PASS.

5. **Report (Extracted / Inferred / Output).**
   - *Output:* tables fixed vs flagged, index notes fixed vs flagged.
   - Call out anything refused by the guard and flagged for human review.
   - Note that tiers are unchanged (this is maintenance, not enrichment).

## Guardrails

- Source content is immutable unless a guard proves the edit is layout-only.
  `apply_repair.py` enforces this; never apply a drifting edit by hand.
- Safe-write: only `generated_by: p2v` notes. `apply_repair.py` refuses others.
- Guarded scope is **table-to-table** (stable table count) and **index de-glue**
  only. Turning prose into a table changes the table count and is rejected by
  design -- flag those as manual cases (the build's deterministic
  `reformat_stat_profiles` already handles the known stat-block ones).
- Repair is outside the determinism guarantee; a later rebuild reproduces the
  original layout, so re-run this skill if needed.
