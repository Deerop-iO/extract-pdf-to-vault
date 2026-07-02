# Verification Harness (reference)

`scripts/verify_vault.py` enforces the contract on a generated vault. It is the
QA gate for `/p2v-build-document` and the whole of `/p2v-verify-vault`.

## Gates (toggle in `verify.config.json`)

- **frontmatter** — every `generated_by: p2v` note has the required keys;
  `source_pages` is `[int, int]`; `tags` is a list containing `pdf-import`.
- **filenames** — each note is either a folder note (stem == folder name) or a
  numbered leaf (`NN[.NN...]-slug`), with a lowercase slug charset. Exactly one
  `index.md` (the library root) is allowed.
- **links** — every internal wikilink is non-bare (contains `/`, except the
  permitted root `index`), aliased, and resolves to an existing note. The
  library-index link is recognized in both forms: bare `index` and the
  qualified Obsidian-root-relative `.../index` used when the vault sits inside a
  larger Obsidian vault (contract §4.1).
- **assets** — every `![](...)` image reference resolves to a file on disk; no
  surviving `ASSET:` sentinel or `http(s)://` reference.
- **reachability** — every generated note is reachable from the library index by
  following wikilinks (so nothing is orphaned).
- **tables** — each markdown table block's data rows agree on column count
  (ignoring the separator). This inconsistency is the validated junk signal
  (e.g. a page number leaked in as an extra column). It deliberately does NOT
  flag all-empty rows (blank form fields) or single-cell numeric rows
  (point-total subtotals) — those are legitimate and `normalize_body` keeps
  them. Detected, never auto-fixed.
- **boilerplate** — fails if any `boilerplate_patterns` regex (from
  `verify.config.json`) still matches a note body. No-op while the list is
  empty. Mirror the list from `pipeline.config.json` to catch anything
  normalization missed.
- **heading_artifacts** — fails if a spaced-out font artifact survived into a
  markdown **heading** (e.g. `## C H A P T E R  F O U R`). Mirrors the
  extractor fix exactly: a heading is flagged iff `collapse_spaced_caps` would
  change it, so it catches a regression of that fix without false-positiving on
  single-letter stat-table column rows (`M WS BS S T W I A`), which are not
  heading lines. Only the unambiguous *fully-spaced* class is flagged; partial
  kerning residue (`T WO`, `F URY`) is a documented limitation, left for human
  review rather than auto-rewritten (see `references/extraction.md`).

## Exit semantics

Exit 0 = all enabled gates pass; exit 1 = one or more failures, each printed as
`[gate] path: message`. Wire it into the build workflow as a blocking step.

## Extending

- Add a gate as a `check_*` function and register it in `GATE_FUNCS` + the
  config defaults. Keep it reading the vault + the pure `lib/` helpers only.
- The determinism gate (rebuild-from-manifest-and-diff) is on the backlog; until
  then, determinism is covered by the kit `tests/` and a manual double-build.

## Extraction-time table data guard (`lib/table_guard.py`)

Separate from this read-only vault harness, a second verifier runs **during
extraction**: `lib/table_guard.data_drift(before, after)`. The structural table
normalizers (`promote_header_below_separator`, `collapse_table_headers`,
`split_am_traits`, `merge_wrapped_table_rows`, `merge_wrapped_name_rows`) are
meant to move only *layout*; the guard proves it by asserting each table's
**DATA-row token multiset is unchanged** (header rows exempt) and hard-failing the
extraction (`SystemExit`, naming the page) on any added/dropped/altered token. It
is on by default (`guard_table_data`) and a no-op when no rule changes anything.
It does not detect pure within-table token reordering (the rules never reorder).

**Demoted-header exemption.** `promote_header_below_separator` legitimately moves
a row *out* of the data region (the `group-row -> separator -> label-row` shape —
see `references/extraction.md`), which a naïve multiset check would read as
dropped data tokens. The guard stays correct because it shares the one predicate
`text._is_demoted_header_table` with the rule: when a table matches that shape,
`_data_rows` **excludes the demoted label row from the data region in the
before-snapshot**, so the promotion is a header move, not a drop — while a genuine
data-row change in the same table is still flagged.

The same function is exposed as a CLI, `scripts/verify_table.py BEFORE.md
AFTER.md` (exit 1 on drift), for the **guarded hand-edit fallback**: for a
weapon chart the deterministic rules cannot fully clean, copy the note's table to
a scratch `before`, hand-reformat it in-agent, run the checker, and apply only
when it reports clean.

## Safe-write interaction

The harness is read-only. The safe-write guarantees (no clobbering user notes,
managed-region-only edits to the library index) live in `build_vault.py`; the
harness just confirms the resulting vault is internally consistent.
