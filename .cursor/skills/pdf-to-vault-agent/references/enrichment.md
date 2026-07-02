# Enrichment (reference)

Enrichment is the **`enriched` tier**, delivered as an agent-driven, post-build
workflow skill (`/p2v-enrich-document`), not as part of the deterministic
pipeline. The Cursor agent itself is the "LLM": it reads already-generated notes
and writes a faithful `summary` and controlled `topic/*` tags.

Structural repair of malformed tables/index is a **separate, tier-neutral** skill
(`/p2v-repair-document`); see [repair.md](repair.md). Fix structure there first,
then enrich.

The authoritative schema lives in `docs/vault-contract.md` (3, 5.2). This
reference explains the discipline and points at the code.

## Where each piece lives in code

- **Frontmatter writer** -- `scripts/apply_enrichment.py`
  (wraps `lib.frontmatter`): the ONLY way the skill writes `summary`/tags, so
  frontmatter never drifts from the contract's key order/quoting. Safe-write:
  refuses non-`generated_by: p2v` notes.

## Summary style (fabrication ban)

- A `summary` is a **faithful condensation of the note's own body** -- one line,
  plain text. It may only restate what the note already says.
- Never add outside knowledge, rules interpretation, or facts not in the note.
  If the body is too thin to summarize, omit the summary (never invent one).
- Summaries are **inferred** and labeled as such: every enriched note carries an
  `enriched` tag, and the build/enrich report lists summaries under *Inferred*,
  separate from *Extracted*.

## Controlled `topic/*` vocabulary (library-scoped)

Topic tags exist to make notes findable; they only help if they are **consistent
across notes and books**. So they are drawn from a controlled vocabulary, not
free-invented per note (which drifts: `topic/melee` vs `topic/close-combat`).

- Tags are appended **after** `pdf-import` and the source slug, never replacing
  them (contract 3). Nested Obsidian tags use `/`, e.g. `topic/melee`.
- Vocabulary file: **`topic-tags.json`, one per library, beside
  `pipeline.config.json`** (NOT in `.p2v/`, which is the extraction source of
  truth). It is shared across every book in that library so tags stay uniform.
- Shape:

```json
{
  "topics": ["topic/melee", "topic/ranged", "topic/psychic", "topic/campaign"]
}
```

- Before tagging, the skill READS this file. It may EXTEND it with a new topic
  only when no existing topic fits, and writes it back deterministically (sorted,
  de-duplicated). It never renames or removes existing topics (that would
  invalidate tags already written into notes).
- If the file is absent, the skill creates it with an empty `topics` list on
  first run.

## Structural repair lives elsewhere

Fixing malformed tables or a glued index is **not** enrichment (it adds no
inferred content). It is the tier-neutral `/p2v-repair-document` skill; its
discipline, both guard invariants, detection, and limits are in
[repair.md](repair.md). Run repair before enriching so summaries describe a
corrected body.
