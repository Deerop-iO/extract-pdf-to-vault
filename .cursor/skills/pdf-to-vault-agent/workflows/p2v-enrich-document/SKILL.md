---
name: p2v-enrich-document
description: Post-build enrichment for a generated vault (enriched tier). Adds a faithful summary and controlled topic tags to note frontmatter. The agent is the LLM; the pipeline stays untouched. Trigger with /p2v-enrich-document.
disable-model-invocation: true
---

# /p2v-enrich-document

Enrich already-generated notes for a single source with a faithful `summary` and
controlled `topic/*` tags. This is the **`enriched` tier**, run in chat AFTER
`build_vault.py` + `verify_vault.py`. It never runs the pipeline, adds no
dependency, and edits frontmatter in place. Read
[references/enrichment.md](../../references/enrichment.md) first; it holds the
discipline (summary style, fabrication ban, vocabulary).

Everything this skill writes is **inferred** -- keep it visibly separate from
*Extracted* in the report.

## Preconditions

- The vault already passes `verify_vault.py` (build + verify done).
- Structure is sound: if a table or index needs fixing, run
  `/p2v-repair-document` **first**, so summaries describe a corrected body.
- You know the source slug and `vault_output` (`pipeline.config.json`).

## Steps

1. **Scope.** Confirm the source slug and vault path. Get the owned note list
   from `.p2v/<slug>.generated.json` (or walk `<vault>/<slug>/`). Only ever touch
   notes whose frontmatter has `generated_by: p2v`. State what you will enrich.

2. **Summary + topic tags (frontmatter, additive).** For each leaf note (and
   optionally folder-note MOCs):
   - Read the controlled vocabulary `topic-tags.json` (beside
     `pipeline.config.json`; create it with `{"topics": []}` if absent). Pick
     `topic/*` tags from it; extend it only when nothing fits, then write it back
     sorted + de-duplicated.
   - Write a faithful one-line `summary` (condensation only -- fabrication ban).
   - Apply via the machine writer, never by hand-editing YAML:
     ```
     python scripts/apply_enrichment.py "<note>" \
       --summary "<one-line summary>" --add-tags "topic/x,topic/y,enriched"
     ```
     With Docker:
     ```
     ./docker-run.sh enrich "<note>" \
       --summary "<one-line summary>" --add-tags "topic/x,topic/y,enriched"
     ```
   - Idempotent: `apply_enrichment.py` skips a note that already has a `summary`
     unless you pass `--force`.

3. **Re-verify.** Run:
   ```
   python scripts/verify_vault.py --vault "<vault>" --config verify.config.json
   ```
   With Docker: `./docker-run.sh verify --vault "<vault>" --config verify.config.json`

   It must stay PASS. The summary shape is checked by the frontmatter gate.

4. **Report (Extracted / Inferred / Output).**
   - *Inferred:* notes summarized, tags added (and any new vocabulary terms).
   - Call out any note left un-summarized (too thin -- never invent one).

## Guardrails

- Fabrication ban: summaries condense the note's own text; tags come from the
  controlled vocabulary; never add outside knowledge.
- Safe-write: only `generated_by: p2v` notes. `apply_enrichment.py` enforces this.
- Structure is out of scope here -- fix broken tables/index with
  `/p2v-repair-document` before enriching.
- Enrichment is outside the determinism guarantee; a later rebuild will clobber
  it. That is accepted -- re-run this skill to restore it (idempotent).
