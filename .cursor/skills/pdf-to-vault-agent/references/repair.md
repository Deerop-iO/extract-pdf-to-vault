# Structural repair (reference)

Repair is a **tier-neutral maintenance** operation, delivered as an agent-driven,
post-build workflow skill (`/p2v-repair-document`), not part of the deterministic
pipeline. The Cursor agent reformats a malformed table or a glued index in an
already-generated note, with every content edit proven **layout-only** by a
deterministic guard. Because nothing is inferred, a repaired note keeps its
current fidelity tier (a `clean` note stays `clean`; repair never makes it
`enriched`).

The authoritative guard contract lives in `docs/vault-contract.md` (5.2). This
reference explains the discipline, detection, and limits, and points at the code.

## Where each piece lives in code

- **Enforced writer** -- `scripts/apply_repair.py`. The ONLY way the skill writes
  a repaired body. It refuses non-`generated_by: p2v` notes (safe-write), runs
  the matching guard on OLD vs NEW body, preserves frontmatter verbatim, and
  writes **only on a clean result** (exit 1 on drift/refusal). For `--kind table`
  it additionally asserts every non-table line is byte-identical old-vs-new, so
  prose outside a table can never be silently changed.
- **Guarded table edits** -- `scripts/verify_table.py --strict`
  (`lib.table_guard.data_drift_strict`): the multiset of data tokens is preserved
  (no token added/dropped/changed) AND data rows are not reordered (row swap).
  Permits boundary-only edits (row merge, column split, header promotion,
  name-wrap merge); rejects a row swap or any data change. Use this standalone for
  a side-by-side preview before applying.
- **Guarded index edits** -- `scripts/verify_index.py`
  (`lib.index_guard.data_drift`): ordered word/page token sequence across
  non-heading lines. Permits de-gluing and letter-group re-heading; rejects a
  page-number swap between terms, or any add/drop. A true A-Z re-sort is out of
  scope (see below).
- **Demoted benefit-table headers** -- `lib/text.promote_demoted_label_row` (runs
  on every clean-tier build) or `apply_repair.py --transform demoted-label-row`
  (post-build): promotes the real label row above the separator on 2-5 column
  tables (`|Selections||| / sep / |Available|…|Cost|`) and emits the spanning
  group title as `**title**` prose immediately above the table so Obsidian
  renders a proper grid. The guard recognises this shape via
  `_is_demoted_label_row_table`, so the title relocation is not flagged as drift.

- **Tables.** The actionable worklist is `verify_vault.py`'s `[tables]` failures,
  so reach for this skill **when the tables gate is failing** (or you eyeball a
  bad table). On an already-passing vault the auto-worklist is empty by
  definition; a **"valid-but-ugly"** table is renderable and therefore only in
  scope when the **user points at it** (documented limitation -- there is no
  auto-detection of ugly-but-valid tables beyond the gate).
- **Index.** Index notes are found by **filename**: an "Index" ToC entry slugs to
  `index`, so index notes are `<num>-index.md` (distinct from the single root
  library `index.md`). Repair them **only where `reconstruct_index` is OFF** for
  that source (`pipeline.config.json`); if it is on, the deterministic
  geometry-based rebuild owns the index at extract time -- skip.

## Why index re-sorting is out of scope

De-gluing preserves reading order, so `index_guard` can prove it changed no data.
A true A-Z re-sort of scrambled multi-column entries, however, *re-associates*
pages to terms -- which cannot be verified from the text alone (a page-swap and a
correct fix look identical to any text-only guard). Genuine re-ordering therefore
belongs to the deterministic, geometry-based `reconstruct_index` (extract time,
`lib.index_layout`). The repair skill only does order-preserving de-gluing/cleanup.

## Guarded scope and its limit

The guarded path is **table-to-table** (stable table count) and **index de-glue**
only. Structure-*creating* transforms -- turning residual prose into a table
(e.g. a run-on stat block) -- change the table count and are rejected by the
guard by design; those stay a flagged/manual case. The build's deterministic
`reformat_stat_profiles` already handles the known stat-block cases at extract
time, so repair rarely needs them.

## Repair loop (contract)

For each candidate: write the proposed new body to a scratch file (a temp dir,
NOT `.p2v/`), run `apply_repair.py` (owned + guard-clean), and it writes **only on
a clean result**; otherwise it refuses and you flag the note for human review. An
ugly-but-correct table beats a pretty-but-wrong one. Source content is immutable
unless a guard proves only layout changed.
