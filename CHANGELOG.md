# Changelog

All notable changes to this kit are recorded here. No versioned releases until
explicitly requested.

## [Unreleased]

### Changed
- Removed `USE_THIS.md`; `AGENTS.md` is the sole agent charter entry point.
- `docs/docker.md`: added **Sharing with colleagues** (repo clone + build, optional
  `docker save`/`load`, optional registry push).

### Added
- **Docker support (`v1.0.1`):** colleagues can now run the pipeline without
  installing Python or a venv. New files: `Dockerfile` (Python 3.11-slim, pinned
  deps, subcommand entrypoint), `docker-entrypoint.sh` (maps `extract` / `build`
  / `verify` / `enrich` / `repair` to the correct scripts), `docker-run.sh`
  (volume-mount wrapper), `.dockerignore` (deny-all, allows only `templates/`).
  `docs/docker.md` explains setup for Docker novices, including the kit-folder
  vs. project-folder distinction and the vault-path constraint. All five workflow
  skills updated with `# With Docker:` command alternatives. `README.md`,
  `AGENTS.md`, and `CLAUDE.md` note the Docker option.

### Added (agent traversal — v1.0.0 polish)
- **Heading-based splitting for no-ToC PDFs (`--fallback headings`):** when a PDF
  has no embedded table of contents, extraction can now reconstruct a flat,
  page-level hierarchy from the markdown heading lines pymupdf4llm's layout
  classifier already emits, instead of the generic one-note-per-page
  (`--fallback pages`) titles. Design and safety:
  - New pure helper `lib/heading_toc.py` (`toc_from_headings`) turns per-page
    markdown into a raw `[[1, title, page], ...]` ToC. **Flat by design** (every
    entry level 1) with **one entry per page** (first heading wins) — the raw
    `#`/`##` depth is intentionally discarded, because feeding it through
    `toc_tree` would nest the whole document under its first heading, and a page
    is the smallest unit this pipeline can split on. Fenced code blocks are
    skipped; emphasis markers are stripped; pages before the first heading get a
    leading `Pages 1-N` entry so no content is dropped.
  - `extract.py` defers the ToC decision for this mode until after
    `to_markdown()` + normalization (headings only exist then), keeps the instant
    fail-fast for the plain no-ToC/no-fallback case, and **hard-stops** (suggesting
    `--fallback pages`) if no usable heading is found — never silently degrading.
    Recorded as `toc_source: "headings"` with an inferred-structure `warning`.
    `split_depth` has no effect in this mode (all entries are level 1).
  - `build_vault.py` renders an `[!note]` callout in the per-PDF MOC when the
    structure was inferred from headings, keeping the extracted-vs-inferred
    distinction visible to the reader.
  - Ships remove the "Phase 2 / deferred" framing for this feature across the
    rules, references, `DEFERRED.md`, and `BACKLOG.md`.
- **Enrichment skill (`/p2v-enrich-document`, `enriched` tier):** an
  agent-driven, post-build workflow that adds a faithful one-line `summary` and
  controlled `topic/*` tags to note frontmatter. The pipeline stays 100%
  deterministic and offline; no LLM API, key, or dependency is added (the Cursor
  agent is the "LLM"). New/changed pieces:
  - **Machine frontmatter writer** — new `apply_enrichment.py` sets `summary` and
    appends tags via `lib.frontmatter` (canonical key order/quoting, safe-write,
    idempotent), so enrichment never hand-emits YAML. `summary` added to
    `frontmatter.KEY_ORDER` (after `tags`); `verify_vault.py` checks it is a
    string when present.
  - **Controlled vocabulary + docs** — `references/enrichment.md` defines the
    summary style, fabrication ban, and the library-scoped `topic-tags.json`
    convention (beside `pipeline.config.json`). `docs/vault-contract.md` gains
    3.1 (optional inferred keys); the router registers `/p2v-enrich-document`.
    (Structural table/index repair was split out into the tier-neutral
    `/p2v-repair-document` skill — see below — so enrichment is now summary + tags
    only.)
- **Repair skill (`/p2v-repair-document`, tier-neutral):** a separate
  agent-driven, post-build workflow that reformats a malformed table or a glued
  index in an already-generated note, with every content edit proven layout-only
  by a deterministic guard. Cheap by design (opens only notes with tables/index,
  never summarizes); because nothing is inferred, a repaired note **keeps its
  current fidelity tier**. New/changed pieces:
  - **Strict table guard** — `lib.table_guard.data_drift_strict` keeps the
    multiset invariant (no data token added/dropped/changed) AND additionally
    rejects a data-row **reordering** (row swap, detected via a row-anchor
    permutation) while still permitting boundary-only edits (row merge, column
    split, header promotion, name-wrap merge); selected via
    `verify_table.py --strict`. The pipeline normalizers keep the looser
    multiset-only `data_drift`. (A pure ordered-token-sequence was rejected: a
    mid-table wrapped-column merge legitimately moves a token ahead of trailing
    columns, so it would false-positive on real repairs.)
  - **Index guard** — new `lib/index_guard.py` + `verify_index.py`: the ordered
    word/page token sequence across non-heading lines must be preserved, so
    de-gluing and letter-group re-heading are allowed but a page-number swap
    between terms (or any add/drop) is rejected. NOTE: a true A-Z re-sort is not
    guard-verifiable and stays the job of the geometry-based `reconstruct_index`;
    the skill de-glues only where `reconstruct_index` is off.
  - **Enforced body writer** — new `apply_repair.py` refuses non-`generated_by:
    p2v` notes, runs the matching guard on old-vs-new body
    (`data_drift_strict` / `index_guard.data_drift`, `--kind`), and writes
    (frontmatter preserved) only on a clean result. For `--kind table` it also
    asserts every non-table line is byte-identical old-vs-new, so prose outside a
    table can never be silently changed. This closes the safe-write gap for body
    edits (the mirror of `apply_enrichment.py` for frontmatter).
  - **Docs** — new `references/repair.md` (repair discipline, both guard
    invariants, detection, tier-neutral note, limits); `docs/vault-contract.md`
    5.2 reframed as tier-neutral guard-gated repair; router registers
    `/p2v-repair-document`.
- **File Explorer sort spec (`sortspec.md`, on by default):** builds now scaffold
  a `sortspec.md` note in the library root, once (never overwritten). Its
  `sorting-spec` frontmatter drives the community plugin **"Custom File Explorer
  sorting"** (`obsidian-custom-sort`) to interleave files and folders in reading
  order (by numeric prefix), fixing Obsidian's default folders-before-files
  display **without** changing the clean `nested` on-disk layout. The rule is
  scoped to the library's own subtree (`target-folder: <path>/*`) so it never
  reorders the rest of a larger Obsidian vault; it falls back to `/*` for a
  standalone vault. The note is user-owned (no `generated_by: p2v`), so user
  edits survive rebuilds and it is exempt from orphan cleanup. View-only; needs
  the plugin installed to take effect. Toggle with `sortspec` in
  `pipeline.config.json` (`lib/naming.py` `sortspec_target`/`sortspec_note`,
  `build_vault.py` `_ensure_sortspec`; documented in `docs/vault-contract.md`
  1.2).

### Changed
- **Demoted benefit-table headers (`promote_demoted_label_row`):** small (2-5
  column) narrative tables whose real column header was pushed below the
  separator (`|Selections||| / sep / |Available|…|Cost|`) are now promoted on
  every clean-tier build: the label row becomes the markdown header, and the
  spanning group title is emitted as `**title**` prose above the table so
  Obsidian renders a proper grid. Guarded via `_is_demoted_label_row_table`
  (shared with `table_guard._data_rows`). Post-build repair:
  `apply_repair.py --transform demoted-label-row`.
- **`verify_vault.py` filenames gate skips user-authored notes:** the naming
  contract now governs only generated notes (frontmatter `generated_by: p2v`),
  mirroring the frontmatter gate. This lets user-owned notes such as `sortspec.md`
  live in the vault without failing verification.

### Fixed
- **Dropped ligature glyphs in table cells (`restore_ligatures`, on by default):**
  pymupdf4llm silently lost the trailing letter of `fi`/`ff`/`fl` ligatures
  *inside table cells*, corrupting text (`fighter` -> `fghter`, `effect` ->
  `efect`, `Fire` -> `Fre`). A spike traced it to a real, present-but-zero-width
  glyph: the `i` of `fighter` arrives as `U+0069` with width `0.0`, and
  pymupdf4llm's per-cell text builder (`helpers.utils.extract_cells`) keeps a
  char only when its bbox overlaps the cell by >50% (`almost_in_bbox`) -- a
  zero-area glyph scores 0% and is dropped. Body text is unaffected; no public
  flag controls it (the chars are identical with `TEXT_PRESERVE_LIGATURES` on or
  off).
  - **Fix:** `extract.py` runtime-patches `almost_in_bbox` (via a scoped context
    manager around the `to_markdown` call) to also keep a degenerate (zero-area)
    glyph whose origin lies inside the cell. This restores a character MuPDF
    *already extracted* -- it never invents one -- so the fabrication ban holds.
    The symbol is imported by value elsewhere, so patching the `utils` module
    attribute affects only the cell-text loop; the patch is restored on exit so
    the process stays pure.
  - **Version-guarded:** if the internal symbol moves on a future pymupdf4llm,
    extraction warns and runs unpatched rather than crashing (re-test on
    dependency bumps). Gated behind a `restore_ligatures` config flag (default
    **on** -- it is a no-op on PDFs without the quirk), recorded in the manifest
    config.
  - **Result on the real vault:** `fghter`/`Efect` artifacts went from
    **109 / 0 / 83** (Core Rulebook / House of Chains / House of Artifice) to
    **0 / 0 / 0**; all 8 verify gates stayed green.

### Added
- **Deterministic table "diff-guard" (`lib/table_guard.py`, on by default):** a
  pure verifier that proves a table reformat changed only *layout*, never data.
  Its invariant: across every structural transform, a table's **DATA-row token
  multiset is preserved** (header rows are exempt, so relabeling a header is
  free). `data_drift(before, after)` compares each table's data tokens and
  reports any token added, dropped, or altered (and table-count mismatches);
  fenced-code blocks are ignored, cell parsing reuses `lib.text._split_cells`.
  Wired into `extract.py`: the structural normalizers run as one guarded group
  (snapshot before, apply rules, then `data_drift` hard-fails the extraction on
  any drift). Gated by `guard_table_data` (default **on**; a no-op when no rule
  changes anything). Documented limitation: a pure within-table *reordering* of
  identical tokens is not detected (the deterministic rules never reorder).
- **Guarded hand-edit CLI (`scripts/verify_table.py`):** `python verify_table.py
  BEFORE.md AFTER.md` runs `table_guard.data_drift` and exits non-zero on drift.
  For the few weapon charts the deterministic rules cannot fully clean, this
  makes an in-agent manual reformat provably safe (advisory check, human applies
  only when clean).
- **Demoted-header promotion (`promote_header_below_separator`, `lib/text.py`,
  opt-in, guarded):** fixes the *dominant* real weapon-chart shape that stopped
  Obsidian from rendering a table at all. pymupdf4llm emits these charts as
  `group-row | separator | label-row`: the markdown header is a near-empty
  spanning row (`||Rng|Rng|Acc|Acc||||||`), the separator follows it, and the
  **real column labels** (`|Weapon|S|L|…|` or `|Grenade|…|`, sometimes with a
  fused `Am Traits`) land *below* the separator as the first data row. Obsidian
  treats the near-empty group row as the header and refuses to render a proper
  table (markdownlivepreview's lenient parser renders it anyway — which is how
  the discrepancy surfaced). The rule folds the group row and the demoted label
  row into one real header above the separator (`Rng` over `S` → `Rng (S)`,
  `Credit` over `Cost` → `Credit (Cost)`), dropping the label row from the data
  region. It then runs *before* `split_am_traits`, so a fused `Am Traits` in the
  promoted header is split normally.
  - **Tight detection:** a `>= 6`-column block whose separator is at row index 1,
    whose header's first cell is empty, and whose first data row is itself a
    weapon-chart header — non-empty item-type label (`Weapon`/`Grenade`/…) plus
    the literal stat-column labels `AP` and `D` and one of `Am`/`Traits`. Those
    header *words* never occur in a data row (data rows hold values like `-1`,
    `4+`), so it cannot fire on real data. Gated, default off (on in the
    Necromunda config), recorded in the manifest config.
  - **Guard kept in lockstep:** this is the "guard refinement" the limitation
    note below called for. Both the rule and `lib.table_guard._data_rows` share
    the one predicate `text._is_demoted_header_table`, so the guard recognises the
    demoted shape and **excludes the label row from the data region in the
    before-snapshot** — the promotion reads as a header move, not a dropped data
    token, while a genuine data-row change in the same table is still caught.
  - **Result on the real vault:** every demoted weapon chart across the three
    Necromunda books (16 headers, incl. the Trading Post `Am Traits`/`Credit`
    charts and the `Grenade` chart) now renders with a proper header; 0 residual
    `||Rng|Rng|…` group rows and 0 fused `Am Traits` headers remain; all 8 verify
    gates green.
- **Three deterministic structural normalizers (`lib/text.py`, opt-in, guarded):**
  `collapse_table_headers` (fold a two-row group+sub header into one
  `Group (Sub)` header — the rarer shape with both header rows *above* the
  separator), `split_am_traits` (split a fused `Am Traits` header column into
  separate `Am`/`Traits` columns across the whole table), and
  `merge_wrapped_name_rows` (fold an orphan weapon-name continuation row into the
  name above, with a sub-header denylist). All pure, idempotent, block-aware,
  `>= 6`-column-gated, and protected by the data guard. Each behind its own
  config flag (default off; enabled in the Necromunda project config), recorded
  in the manifest config.
  - **Earlier limitation, now resolved:** on first ship, the dominant
    `group-row -> separator -> label-row` weapon-chart shape was a no-op for
    `collapse_table_headers` / `split_am_traits` (they assume the real header is
    the markdown header). `promote_header_below_separator` (above) + the shared
    guard predicate now handle that shape; `split_am_traits` runs on the promoted
    header and cleans the fused `Am Traits` column.
- **Wrapped weapon-table row merging (opt-in):** Necromunda weapon reference
  charts (per-house weaponry + the Trading Post) extract as valid-but-ugly
  markdown tables -- a long `Traits` list (sometimes fused with the `Am` column)
  overflows onto a following near-blank row, splitting each weapon's traits in
  two in Obsidian. A new pure `lib/text.merge_wrapped_table_rows` folds those
  continuation rows back into the row above.
  - **Header-independent, comma-anchored:** pymupdf4llm is inconsistent about
    keeping `Am`/`Traits` separate vs. fused, so the wrapped cell's index varies.
    Detection therefore ignores headers: a row is a continuation iff it has
    exactly one non-empty cell and the previous row's cell in that same column
    either (a) ends with a comma (the usual line-wrap signal) or (b) ends with
    the first word of a known two-word Necromunda trait that the continuation
    cell completes (e.g. `...Knockback, Shield` + `Breaker, Shock` ->
    `Shield Breaker`; the comma falls *inside* the trait so (a) misses it). The
    case-(b) allowlist (`_MULTIWORD_TRAITS`) is drawn from the rulebook's own
    trait glossary (section 1.60): `Shield Breaker`, `Single Shot`, `Rapid Fire`,
    `Energy Shield`, `Assault Shield`, `Chem Delivery`, `Graviton Pulse`. A
    point-total subtotal, a blank form row, a section-label row, and a wrapped
    weapon *name* all fail the test. A >= 6-column block guard keeps it off small
    narrative tables. Idempotent; re-joins existing text only (never edits
    spelling or relabels headers).
  - **Gated** behind a new `merge_wrapped_table_rows` config flag (default off;
    set only in the Necromunda project config). Wired into `extract.py`'s
    per-page normalize step after `reformat_stat_profiles`, recorded in the
    manifest config.
  - **Result on the real vault:** every comma-terminated *and* mid-trait
    weapon-`Traits` continuation merged across the Core Rulebook, House of Chains,
    and House of Artifice -- including all 5 `Shield Breaker` rows in the Trading
    Post (the 2 mid-trait wraps that the comma rule alone could not reach); all 8
    verify gates stayed green. Known residue (left untouched by design): the
    garbled multi-column *prose* tables (gang-tactics cards, skill/agility text,
    scenario tables) -- a separate extraction artifact that is explicitly out of
    scope.
- **Necromunda vehicle stat-profile reformatting (extends the opt-in normalizer):**
  `lib/text.reformat_stat_profiles` now also recognizes the canonical vehicle
  profile (`M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int` + 12 values) in
  addition to the fighter profile, under the same `reformat_stat_blocks` flag.
  - **Same shape, same safety:** vehicle profiles are also fixed 12-column rows
    with the same value grammar; the fighter and vehicle headers are mutually
    exclusive, so detection is unambiguous. The 12-valid-tokens-or-abort guard,
    `|`/`#` passthrough, bold/`<br>` handling, and idempotency all carry over.
  - **Refactor is behavior-preserving for fighters:** the per-profile header is
    now built by `_profile_header(cols)`, which reproduces the original fighter
    regex byte-for-byte (pinned by a unit test); all prior fighter tests pass
    unchanged.
  - **No regression on the real vault:** re-extracting the Core Rulebook, House
    of Chains, and House of Artifice produced content-identical manifests (all
    vehicle profiles in these books are already ruled tables), and all 8 verify
    gates stayed green. Vehicle support is future-proofing for vehicle-heavy
    books (e.g. Ash Wastes), where vehicle profiles render run-on like fighter
    gang lists. Run-on weapon profiles remain out of scope (variable-width
    name + free-text Traits is a different problem).
- **Necromunda fighter stat-profile reformatting (opt-in):** Necromunda PDFs
  render the fixed 12-column fighter profile (`M WS BS S T W I A Ld Cl Wil Int`
  + values) -- and the fighter name/cost above it -- as one run-on TEXT line, so
  neither `table_strategy="lines_strict"` nor `"text"` turns it into a grid (the
  `"text"` strategy was trialled on all three books and changed nothing). A new
  pure `lib/text.reformat_stat_profiles` reformats only that exact shape into a
  markdown table.
  - **Additive and conservative:** skips lines already starting with `|`
    (existing tables) or `#`; aborts on any line whose 12 post-header tokens are
    not all valid values (`4"`, `4+`, `10+`, bare int, `-`), so it can neither
    corrupt prose nor disturb profiles pymupdf4llm already tabled. Handles bold
    headers (`**M WS ...**`) and `<br>`-split header/values; idempotent.
  - **Gated** behind a new `reformat_stat_blocks` config flag (default off; set
    only in the Necromunda project config). Wired into `extract.py`'s per-page
    normalize step (clean/enriched tiers), recorded in the manifest config.
  - **Result on the real vault:** the 30 run-on profiles across the Core
    Rulebook, House of Chains, and House of Artifice all became tables (working
    profile tables 15 -> 45), the pre-existing ruled tables were untouched, and
    all 8 verify gates stayed green. Bolt Action / Frostgrave and the kit
    template config are unaffected (flag off).
- **Branch-section preamble capture (real Necromunda gang lists):** a chapter
  whose only bookmarked child sits partway through it (e.g. `1.8 House Van Saar
  Gang List`, pages 34-50, whose sole subsection `1.8.1 Exotic Beasts` starts on
  page 49) no longer drops the pages before that child. The leaf/branch split
  previously gave a branch only a Contents MOC, discarding pages 34-48 entirely.
  - **`toc_tree.branch_preamble_range(node, sections)`** (pure): the page range
    `[start, first_child_start - 1]` a branch owns before its first child, or
    `None` when it is a leaf / childless / a child shares its start page.
  - **`extract.py`** now slices that preamble into the branch's `markdown`/
    `assets` (reusing the same per-page data and shared-page warning path as
    leaves); preamble pages never overlap child pages, so nothing is captured
    twice.
  - **`build_vault.py`** renders the preamble above the branch note's Contents
    list (the injected `# Title` H1 is kept; a near-duplicate PDF heading in the
    preamble is left as-is, not fuzzily de-duped), copies branch-referenced
    assets, and sanitizes any section carrying `markdown`.
  - **Backward-compatible**: the manifest gain is additive. A pre-fix manifest
    (no branch `markdown`) rebuilds byte-identically to before — existing vaults
    only change when their PDFs are deliberately re-extracted. Locked by a
    backward-compat render test and an end-to-end idempotency smoke test.
  - **`source_pages`** on a branch stays the full chapter span; only the body is
    the preamble subset (reconciled in `vault-contract.md` §5).
- **Spaced-caps heading artifacts (real Frostgrave rulebook):**
  - **Heading-scoped spaced-caps collapse** (`lib/text.collapse_spaced_caps`,
    wired into `normalize_body`). PDF kerning renders some titles glyph-by-glyph
    (`C H A P T E R  F O U R`); this collapses fully-spaced runs back to
    `CHAPTER FOUR`. Applied **only to markdown heading lines** (and never inside
    fenced code), because a single-letter stat-table column run
    (`M WS BS S T W I A`) is data, not a spaced word, and must never be
    collapsed. Idempotent.
  - **`heading_artifacts` verifier gate** (`verify.config.json`): fails if a
    fully-spaced artifact survived into a heading. Mirrors the fix exactly (a
    heading is flagged iff `collapse_spaced_caps` would change it), so it catches
    a regression without false-positiving on stat rows (not heading lines).
  - **Per-source config overrides**: an optional `sources` map in
    `pipeline.config.json`, keyed by `source_slug`, is merged over the global
    config — so one PDF can carry its own `boilerplate_patterns` / `tier` /
    `split_depth` (or `table_strategy`) without affecting the others.
  - **`table_strategy` pass-through** to `pymupdf4llm.to_markdown`
    (signature-guarded like `header`/`footer`). Defaults to `"lines_strict"`
    (the library default, so existing extractions are byte-identical); set
    `"text"` per source to recover stat blocks that render as plain spaced text
    instead of ruled tables. Recorded in the manifest config.
  - **End-to-end smoke test** (`tests/test_smoke.py`): builds a tiny fixture PDF
    with PyMuPDF (embedded ToC + a stat line), runs extract -> build -> verify,
    and asserts all gates pass and the stat line survives. Skips cleanly when
    PyMuPDF / pymupdf4llm are not installed, so the lightweight `lib/` suite
    still runs everywhere.
  - **Known limitation** (documented, not auto-fixed): partial kerning residue
    where two glyphs fused (`T WO`, `F URY`) is left for human review. A rule
    aggressive enough to join `F URY` -> `FURY` would also corrupt legitimate
    text such as `(A OR B)` -> `(AORB)` or `A NEW ERA` -> `ANEW ERA`, so only the
    unambiguous fully-spaced class is collapsed.
- **Kit hardening (three failure classes seen in real vaults):**
  - **PDF artifact normalization** (extraction layer, clean/enriched tiers
    only). `lib/text.normalize_body` strips injected boilerplate (e.g. a DRM
    "This ebook belongs to…" watermark, incl. fragments fused into table
    cells), the furniture residue left where a fragment was excised (e.g. a
    stray `187<br>`), and standalone page-number *lines* (bounded by page
    count). New `pipeline.config.json` keys `header`/`footer` (passed through to
    `pymupdf4llm.to_markdown`, signature-guarded), `boilerplate_patterns`, and
    `strip_page_numbers`. The normalization config is recorded in the manifest.
    Removes only provable junk: it **never** deletes a table row on a
    numeric/empty heuristic (point-total subtotals like `|||||504|` and blank
    character-sheet form rows are kept); the only row removal is a row excision
    emptied itself. Column-shifted tables are detected, never auto-rewritten.
    Idempotent and code-fence-aware.
  - **Two new verifier gates** (`verify.config.json`): `tables` (flags only
    data rows that disagree on column count — not all-empty rows or single-cell
    numeric rows, which are legitimate) and `boilerplate` (no configured pattern
    survives into a note body; no-op until `boilerplate_patterns` is set).
  - **`tools/clean_existing_vault.py`** — a reusable, body-only maintenance
    tool that reuses `normalize_body` (with `strip_page_numbers=False`) to clean
    boilerplate out of vaults built before normalization existed. Dry-run by
    default; `--patterns-file` (gitignored, keeps PII out of tracked config),
    `--report` unified-diff log, optional `--backup-dir`; idempotent; flags
    picture-text blocks carrying non-watermark content for review.
  - **Library-index link disambiguation** (`library_index_link: auto|root`).
    When the vault lives inside a larger Obsidian vault, the per-PDF MOC's
    `parent` now links to the index by its Obsidian-root-relative path
    (`naming.obsidian_relative_index`), fixing the wrong-library `[[index]]`
    collision. Standalone output keeps the bare `[[index]]` link unchanged. The
    verifier recognizes both forms.
- Phase 1 kit: deterministic PDF -> Obsidian vault pipeline.
- `docs/vault-contract.md` (single source of truth) and
  `docs/extraction-manifest.md` (manifest schema).
- `templates/scripts/` pipeline: `extract.py`, `build_vault.py`,
  `verify_vault.py`, and pure `lib/` helpers (`slugify`, `toc_tree`,
  `naming`, `frontmatter`, `links`).
- Templates config: `requirements.txt` (pinned), `pipeline.config.json`,
  `verify.config.json`, `_templates/` Obsidian note templates, `.env.example`.
- Always-on rules under `.cursor/rules/` and the `pdf-to-vault-agent` router
  skill with `references/` and `/p2v-*` workflows
  (`p2v-start-project`, `p2v-build-document`, `p2v-verify-vault`).
- Kit `tests/` exercising the `lib/` helpers (now incl. `TestNormalizeBody`
  covering subtotal/blank-row safety, excision residue, and idempotency;
  `TestVerifyGates` for the `tables`/`boilerplate` gates; and
  `naming.obsidian_relative_index`, covering both standalone and in-Obsidian
  vault link modes).

### Fixed
- **`to_markdown` pass-through on pymupdf4llm 1.27+**: that version wraps
  `to_markdown` as `(*args, **kwargs)`, so the old name-only signature guard
  found no parameters and silently dropped `header`/`footer`. `extract.py` now
  also forwards the pass-through keys (`header`, `footer`, `table_strategy`) when
  the signature exposes a `**kwargs` catch-all, and still warns (never crashes)
  on an explicit older signature that genuinely lacks a key.
- **Library-index dedup** (`build_vault.py` `_update_library_index`) now drops
  all prior entries whose leading slug segment matches the source, not just the
  exact current MOC target. An older build (or a different link convention) could
  leave a stale bare `[[<slug>]]` beside the qualified `[[<slug>/<slug>]]`;
  keying on the slug segment prevents the duplicate from surviving a rebuild.
- **Stale/moved vault warning** (`build_vault.py`): when `--vault` differs from
  the vault recorded in `<slug>.generated.json`, the build warns that orphan
  cleanup only runs under the current vault, so files left at the old location
  are surfaced instead of silently stranded.
- `verify_vault.py` now ignores scaffolding/config directories (`_templates/`,
  `.p2v/`, `.obsidian/`, and dot/`_`-prefixed dirs) so the default vault
  skeleton and Obsidian internals do not trip the gates.
- Sanitize control characters (notably NUL bytes from UTF-16 PDF bookmark
  titles) from titles and body text (`lib/text.py`, wired into `extract.py` and
  `build_vault.py`). Previously these corrupted YAML frontmatter and made notes
  read as binary. Caught by the verification harness on a real 321-page rulebook.
- `build_vault.py` now reclaims files recorded in the prior
  `<slug>.generated.json` as owned, so a re-build/refresh can safely overwrite
  its own previous output even if that output's frontmatter got corrupted.

### Verified
- End-to-end smoke test on a synthetic ToC PDF and a real 58-page PDF:
  deterministic re-runs are byte-identical, the safe-write guard refuses to
  clobber user-authored notes, the library index managed region preserves user
  content, and all consistency gates pass.
- Spaced-caps work revalidated on the real 225-page Frostgrave rulebook
  (rebuild + verify PASS on all gates incl. `heading_artifacts`) and on
  Necromunda (PASS — confirming the new gate does not false-positive on
  stat-table data, which is not on heading lines). The stale-vault warning was
  exercised against a throwaway temp vault.
