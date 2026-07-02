# Extraction

Deep reference for stage 1 (`scripts/extract.py`). The manifest it produces is
the source of truth; see `docs/extraction-manifest.md` for the schema.

## Tool surface (verify against Context7 `/pymupdf/pymupdf4llm`, `/pymupdf/pymupdf`)

- `fitz.open(path)` -> document. `doc.get_toc(simple=True)` returns
  `[[level, title, start_page], ...]` (1-based pages). `doc.metadata` gives
  `title`, `author`. `doc.page_count` is the page total.
- `pymupdf4llm.to_markdown(path, page_chunks=True, write_images=True,
  image_path=<staging>, image_format="png")` returns one dict per page, in
  document order, each with `metadata`, `toc_items`, `text` (markdown), `images`,
  `tables`, `graphics`, `page_boxes`.
- `to_markdown` also takes `header` / `footer` (both default `True`), which is
  *why* running headers and page-number footers show up. `extract.py` passes the
  config values through **only if the installed signature has them** (guarded by
  `inspect.signature`), and otherwise warns instead of crashing. `footer=False`
  is the cleanest source-level removal of page numbers / running headers.
- Chunks come back **in page order**; the extractor uses the enumerate index
  (`i + 1`) as the 1-based page number rather than trusting a metadata field,
  which is robust across versions.

## What extract.py does

1. Open the PDF; read metadata, page count, sha256.
2. Get the ToC. Apply the source-precedence ladder:
   - Embedded ToC present + `--ignore-toc` not set → use it (`toc_source=embedded`).
     If `--fallback` was also passed, emit a notice and ignore the flag. If the
     embedded outline looks degenerate (`embedded_toc_looks_degenerate`: ≥ half
     of titles are bare page numbers, or all level-1 with numeric-only titles),
     emit a suggestion to re-run with `--ignore-toc --fallback toc` — but still
     use the embedded ToC (no auto-switch).
   - `--ignore-toc` set → drop the embedded outline; fall through to `--fallback`.
   - No embedded ToC or `--ignore-toc` in effect → require `--fallback`.
     `--fallback toc` defers ToC-page reconstruction until per-page markdown is
     ready (step 5b). `--fallback headings` / `--fallback pages` set `toc_source`
     immediately. All three are opt-in.
   - Hard-stop with an actionable message if no ToC and no `--fallback`.
3. Optionally clamp ToC depth (`split_depth`).
4. Run `to_markdown(page_chunks=True, write_images=True)` into a staging dir.
   The `header`, `footer`, and `table_strategy` config keys are forwarded as
   pass-through kwargs (via `_select_passthrough`, which honors both explicit
   signatures and the `(*args, **kwargs)` wrapper that pymupdf4llm 1.27+ uses).
   `table_strategy` defaults to `"lines_strict"` (the library default, ruled
   tables); `"text"` recovers some position-based grids, but note it did **not**
   recover Necromunda's run-on fighter/vehicle profiles (use
   `reformat_stat_blocks` for those -- see "Necromunda stat profiles" below).
   When `restore_ligatures` is set (default on), this call is wrapped in a scoped
   patch that stops pymupdf4llm dropping zero-width ligature glyphs in table
   cells -- see "Dropped ligature glyphs in table cells" below.
5b. **ToC-page reconstruction (`--fallback toc`)** — executed here, now that
   per-page markdown is available. Find the ToC start page by matching
   `toc_title_pattern` (config regex) against page headings, or use `--toc-page N`
   to pin it. Extend the run to contiguous pages that still contain dot-leader
   rows. Extract fragment geometry via `_page_fragments` and call
   `lib.toc_page.toc_from_toc_page(frags, page_texts, hierarchy_mode)`:
   - **Row assembly**: cluster fragments by y-baseline, concatenate left-to-right,
     strip dot leaders, peel the trailing integer as `printed_page`.
   - **Dual-mode level inference** (mode from `toc_hierarchy_mode` config):
     `indent` clusters `x0` into bands; `numbered` parses outline prefixes;
     `auto` picks numbered when ≥ 60 % of rows carry a prefix.
   - **Offset detection**: samples ToC titles against page headings (normalized
     substring match) to find `physical = printed + offset` (modal vote). Warns
     if fewer than 2 matches or offset is inconsistent; uses 0 as safe default.
   - Hard-stop (not flatten) if the ToC page produces no usable structure.
   - Sets `toc_source = "toc-page"` and records a `warning` (inferred).
5. Rewrite each markdown image reference to an `ASSET:<basename>` sentinel
   (portable). Collect per-page asset basenames.
5b. **Normalize the body** (clean/enriched tiers only; `structural` keeps raw
   text) via `lib/text.normalize_body` (and, when `reformat_stat_blocks` is set,
   `lib/text.reformat_stat_profiles`; then the gated structural table
   normalizers run as one **guarded group** -- `promote_header_below_separator`,
   `collapse_table_headers`, `split_am_traits`, `merge_wrapped_table_rows`,
   `merge_wrapped_name_rows`, each toggled by its own flag -- after which, when
   `guard_table_data` is set
   (default on), `lib/table_guard.data_drift` hard-fails the extraction if any
   table DATA-row token changed. See "Necromunda stat profiles", "Wrapped
   weapon-table rows", and "Structural table normalizers + data guard" below):
   drop lines that are only
   `boilerplate_patterns` (e.g. a DRM watermark), excise such fragments embedded
   inside a line/table cell (dropping the line only if excision left nothing but
   furniture), and — when `strip_page_numbers` — drop **standalone** page-number
   *lines* (bounded by `page_count`). It **never** deletes a table row on a
   numeric/empty heuristic: a single-cell numeric row may be a subtotal and an
   all-empty row may be a blank form field. The only row removal is a row the
   excision step emptied itself. Ambiguous column-shift tables are left for the
   verifier's `tables` gate, never auto-rewritten (fabrication ban). It also
   collapses spaced-out font artifacts (`C H A P T E R` -> `CHAPTER`) via
   `collapse_spaced_caps`, but **only on markdown heading lines** — a single-
   letter stat-table column run (`M WS BS S T W I A`) is data, not a spaced
   word, and must never be collapsed. Only fully-spaced runs are fixed; partial
   kerning residue (`T WO`, `F URY`) is left untouched because a rule that joins
   `F URY` -> `FURY` would also corrupt legitimate text like `(A OR B)` ->
   `(AORB)`. The `heading_artifacts` verify gate flags the fully-spaced class.
6. Scanned guard: if total text < `min_text_chars`, stop (OCR is opt-in).
7. Build the positional section tree (`lib/toc_tree.build_sections`), assign each
   leaf its page-range markdown and assets.
8. Write `.p2v/<slug>.manifest.json` and stage assets in
   `.p2v/<slug>.assets/`.

## Per-source config overrides

A single `pipeline.config.json` can carry an optional `"sources"` map keyed by
`source_slug`; its values are merged over the global config once the slug is
known. This lets one shared config give a DRM-stamped PDF its own
`boilerplate_patterns`, or a Necromunda book its own `reformat_stat_blocks: true`
(to turn run-on fighter/vehicle profiles into tables -- see below), or a different
`tier` / `split_depth` — without affecting the others:

```json
{
  "tier": "clean",
  "sources": {
    "bolt-action-third-edition": {
      "boilerplate_patterns": ["(?im)^.*proof copy.*$"]
    },
    "necromunda-core-rulebook-2023": {
      "reformat_stat_blocks": true
    }
  }
}
```

Note: `slug_max_len` is used to derive `source_slug` *before* the merge, so
overriding it per-source has no effect on the slug itself.

## Necromunda stat profiles (`reformat_stat_blocks`)

Necromunda PDFs render a fixed 12-column characteristic profile -- and the
name/cost above it -- as a single run-on **text** line, not a ruled grid.
Neither `table_strategy="lines_strict"` nor `"text"` recovers it (the `"text"`
strategy was trialled across all three books and changed nothing). Set
`"reformat_stat_blocks": true` (globally in a Necromunda project config, or
per-source) to run `lib/text.reformat_stat_profiles` after `normalize_body` on
the clean/enriched tiers. Two canonical profiles are recognized:

- **fighter:** `M WS BS S T W I A Ld Cl Wil Int`
- **vehicle:** `M Front Side Rear HP Hnd Sv BS Ld Cl Wil Int`

Both are 12 columns, both end in `Wil Int`, and the two headers are mutually
exclusive (after `M`, a fighter has `WS`, a vehicle has `Front`). It reformats
**only** those exact shapes into a markdown table and is deliberately narrow:

- Skips lines already starting with `|` (existing tables) or `#`; matches a bold
  (`**...**`) or plain header, with values optionally split off by `<br>`.
- Requires the 12 post-header tokens to all be valid values (`4"`, `4+`, `10+`,
  a bare integer, or `-`); otherwise the line is left untouched -- it never
  partially splits a line (fabrication ban). Idempotent.
- Emits the name/cost on its own line, then the 12-column table, then any
  trailing text. Profiles pymupdf4llm already tabled are never touched, so the
  pass only ever *adds* tables. (In the current three books every vehicle
  profile is already a ruled table; vehicle support is future-proofing for
  vehicle-heavy books such as Ash Wastes, where they render run-on like fighter
  gang lists.)

Default off; the kit template config does not set it, so non-Necromunda books
are unaffected.

## Wrapped weapon-table rows (`merge_wrapped_table_rows`)

Necromunda weapon reference charts (per-house weaponry + the Trading Post)
extract as valid-but-ugly markdown tables: a long `Traits` list overflows onto a
*following* row whose only non-empty cell is that column, while the row above
ends that cell with a trailing comma. Obsidian then renders a near-blank row
that splits each weapon's traits in two. Set `"merge_wrapped_table_rows": true`
(globally in a Necromunda project config, or per-source) to run
`lib/text.merge_wrapped_table_rows` after `reformat_stat_profiles` on the
clean/enriched tiers. It folds each continuation row back into the row above.

Detection is **header-independent by design**: pymupdf4llm is inconsistent about
whether `Am` and `Traits` stay separate columns or fuse into one (e.g.
`4+ Limited, Rapid Fire (1),`), so the wrapped cell's index varies between
sibling sub-tables. Rather than trust a header label, a row is treated as a
continuation iff:

- it has **exactly one** non-empty cell, and
- the previous row's cell in that **same column** either (a) ends with a comma --
  the usual line-wrap signal -- or (b) ends with the first word of a known
  two-word trait that the continuation cell completes (e.g.
  `...Knockback, Shield` + `Breaker, Shock` -> `Shield Breaker`; the comma falls
  *inside* the trait so (a) misses it), and
- the table block is **>= 6 columns** wide (keeps it off narrow narrative tables).

The case-(b) allowlist (`_MULTIWORD_TRAITS`) is drawn from the rulebook's own
trait glossary (section 1.60) and is intentionally small: `Shield Breaker`,
`Single Shot`, `Rapid Fire`, `Energy Shield`, `Assault Shield`, `Chem Delivery`,
`Graviton Pulse`. It only ever recognises a wrap of a real trait; an unknown
two-word phrase (e.g. `Shield` + `Wall`) is never merged.

The merged cell is the previous cell + `" "` + the continuation cell; the
continuation row is dropped. This re-joins text already present -- it never edits
spelling, relabels headers, or invents content (fabrication ban). It is
idempotent. A point-total subtotal (value in the Cost column), a blank form row
(no non-empty cell), a section-label row, and a wrapped weapon *name* all fail
the test.

Known residue it deliberately leaves alone: the garbled multi-column **prose**
tables some books produce (gang-tactics cards, skill/agility text, scenario
tables) are a separate extraction artifact, out of scope, and are protected by
the column guard / detection rule. Default off; the kit template config does not
set it.

## Dropped ligature glyphs in table cells (`restore_ligatures`)

pymupdf4llm silently loses the trailing letter of an `fi`/`ff`/`fl` ligature
**inside table cells**, corrupting text (`fighter` -> `fghter`, `effect` ->
`efect`, `Fire` -> `Fre`). The cause is not a font/encoding defect: `get_text`
returns the word correctly. The `i` of `fighter` is a real but **zero-width**
glyph (`U+0069`, advance `0.0`), and pymupdf4llm's per-cell text builder
(`helpers.utils.extract_cells`) keeps a char only when its bbox overlaps the cell
by >50% (`almost_in_bbox`) -- a zero-area glyph scores 0% and is dropped. Body
text is unaffected, and **no public flag controls it** (the chars are identical
with `TEXT_PRESERVE_LIGATURES` on or off).

With `"restore_ligatures": true` (the default), `extract.py` wraps the
`to_markdown` call in a scoped context manager that runtime-patches
`almost_in_bbox` to also keep a degenerate (zero-area) glyph whose origin lies
inside the cell. That restores a character MuPDF *already extracted* -- it never
invents one -- so the fabrication ban holds. `almost_in_bbox` is imported by
value into the other helper modules, so patching the `utils` module attribute
affects only the cell-text loop; the original is restored on exit so extraction
stays pure. The patch is **version-guarded**: if the internal symbol moves on a
future pymupdf4llm, extraction warns and runs unpatched rather than crashing
(re-test on dependency bumps). It is a no-op on PDFs without the quirk, which is
why it defaults on. On the real vault it took `fghter`/`Efect` artifacts from
109 / 0 / 83 (Core Rulebook / House of Chains / House of Artifice) to 0 / 0 / 0.

## Structural table normalizers + data guard (`guard_table_data`)

Further opt-in weapon-chart cleanups live in `lib/text.py`, all pure,
idempotent, block-aware, and `>= 6`-column-gated like `merge_wrapped_table_rows`:

- `promote_header_below_separator` — fix the *dominant* real shape where the
  separator sits at row index **1**, the markdown header is a near-empty spanning
  group row (`||Rng|Rng|Acc|Acc||||||`), and the **real column labels land below
  the separator** as the first data row (`|Weapon|S|L|…|` or `|Grenade|…|`). Fold
  the group row and the demoted label row into one header above the separator
  (`Rng` over `S` -> `Rng (S)`, `Credit` over `Cost` -> `Credit (Cost)`) and drop
  the label row. Runs **first**, so a fused `Am Traits` it surfaces in the header
  is then split by `split_am_traits`. Detection is tight: empty header first cell
  + a first data row carrying a non-empty item-type label and the literal stat
  labels (`AP`, `D`, and `Am`/`Traits`) — words that never occur in a data row.
- `collapse_table_headers` — fold a two-row header (a spanning group row sitting
  directly above the real header, with the separator at row index **2** — the
  rarer shape) into one `Group (Sub)` header (`Range` over `S` -> `Range (S)`);
  drop the group row if column counts do not align. Header-only.
- `split_am_traits` — when the **markdown header row** carries a single fused
  `Am Traits` column, split it into `Am` + `Traits` across header, separator, and
  every data row (leading ammo token `5+`/`2`/`-` -> `Am`; remainder -> `Traits`).
  Keeps the table rectangular; token-preserving in the data region.
- `merge_wrapped_name_rows` — fold an orphan row whose only non-empty cell is the
  first (Weapon) column into the complete data row above it (`- photon flash` +
  `grenades`), skipping sub-headers (italic emphasis, `combi-weapon`/`component`/
  `pattern`, ALL-CAPS labels). The most heuristic rule; leans on the guard.

**The data guard (`lib/table_guard.py`, `guard_table_data` default on).** The
structural rules run as one group in `extract.py`: snapshot the page text, apply
the gated rules in order, then `table_guard.data_drift(before, after)` asserts
every table's **DATA-row token multiset is unchanged** (header rows exempt) and
`raise SystemExit` on any added/dropped/altered token, naming the page. It is a
no-op when nothing changed. Pure within-table token *reordering* is not detected
(the rules never reorder). The same function backs `scripts/verify_table.py`
(`python verify_table.py BEFORE.md AFTER.md`), the advisory checker for the
guarded in-agent hand-edit fallback on charts the rules cannot fully clean.

**The `group-row -> separator -> label-row` shape (resolved).** This dominant
Necromunda extraction shape — markdown header = spanning group row, separator
next, real labels below the separator in the data region — is exactly what
`promote_header_below_separator` now repairs, so Obsidian renders these charts as
proper tables. The "guard refinement" it needs is built in: the rule and
`table_guard._data_rows` share one predicate, `text._is_demoted_header_table`, so
the guard **excludes the demoted label row from the data region in the
before-snapshot**. Promotion therefore reads as a header move (not a dropped data
token), while a genuine data-row change in the same table is still caught.
`collapse_table_headers` / `split_am_traits` continue to handle the rarer
both-rows-above-separator shape and the fused `Am Traits` column (the latter on
the now-promoted header).

## Printed ToC-page reconstruction (`--fallback toc`)

Use when the PDF has no embedded ToC, or when the embedded one is degenerate
(e.g. bare page-number titles). Requires `--ignore-toc` if an embedded ToC is
present (even a degenerate one). Never auto-activates.

**Invocation:**

```
python extract.py book.pdf --ignore-toc --fallback toc
python extract.py book.pdf --ignore-toc --fallback toc --toc-page 2
```

**Config keys (add to `pipeline.config.json` or per-source `sources` map):**

```json
"toc_title_pattern": "regex matching the ToC page heading (case-insensitive)",
"toc_hierarchy_mode": "auto | indent | numbered"
```

Default `toc_title_pattern` covers: *contents, table of contents, toc, index,
inhoudstafel, inhoudspgave, inhaltsverzeichnis, table des matières, índice,
contenido*. Override per source in the `sources` map.

**Fidelity tier:** `toc-page` is geometry-inferred, not extracted from the PDF's
outline chain. The hierarchy is labeled `inferred` in `warnings` and the MOC.
Page boundaries remain page-level (no intra-page precision), and shared-page
warnings still apply when many sections start on the same physical page.

**Offset caveat:** When a document has unnumbered front matter, printed page
numbers on the ToC differ from physical page indices. The auto-detection
matches a sample of titles against headings in the per-page markdown and takes
the modal `physical - printed` value. Check the `toc-page: could not match…`
and `toc-page: page offset inconsistent…` warnings if section page ranges look
wrong; use `--toc-page N` combined with a manual `toc_page_offset` override in
a future version if needed.

**Scanned/image ToC pages:** Not supported. The module reads text fragments from
PyMuPDF; a scanned page with no selectable text returns no rows and the
extraction hard-stops. Run OCR first (opt-in).

## Back-of-book index reconstruction (`reconstruct_index`)

A printed alphabetical index is laid out in N columns, each an independent A–Z
stream of `term … page-numbers` rows. A flat text/markdown reader walks each
printed line **left-to-right across the columns** and concatenates, which both
glues unrelated entries onto one line and scrambles the letter order (the true
reading order is column-by-column, not row-by-row). pymupdf4llm also leaks the
giant `INDEX` title, running headers/footers, and image alt-text into the body.

With `"reconstruct_index": true` (opt-in, per source via the `sources` map),
`extract.py` rebuilds any **leaf** section whose control-char-stripped ToC title
matches `index_title_pattern` (default `^\s*index\s*$`). It re-reads that
section's pages as positioned spans (`page.get_text("dict")` →
`blocks[].lines[].spans[]`, using `bbox`/`size`/`flags`; bold = `flags & (1<<4)`,
verified against Context7 `/pymupdf/pymupdf`) and hands them to
`lib/index_layout.reconstruct_index`, which:

1. Picks a **column template** — the band layout from whichever index page
   detects the cleanest (most) columns via coverage gutters — and applies it to
   every index page, so pages whose gutters are bridged by dotted leaders still
   split correctly.
2. Keeps only the dominant (entry) font size, plus the larger single-letter
   section heads; this drops the title, the page-number footer, and the running
   header without guesswork.
3. Reads each column top-to-bottom, emits columns left-to-right and pages in
   order — i.e. true A–Z — as `## INDEX`, `### A … ### Z` headings, and one
   `- entry` per line with dotted leaders stripped.

The section is tagged `"kind": "index"` and its page numbers stay **plain text**.
`build_vault._linkify_index_body` then turns each page number into a
vault-relative aliased wikilink to the note covering that page
(`_page_targets`: leaves win over branches), a range/comma-list links its first
page, bold "main reference" numbers keep their emphasis, and when the entry term
matches a heading in the target note the link carries that **heading anchor**
(`note#HEADING`). `verify_vault` strips the `#anchor` before resolving, so these
pass the `links`/`reachability` gates.

It is geometry-driven **reformatting** of already-extracted text — it never
invents a term, page number, or ordering (fabrication ban). If the flag is on
but no section matches, or a matched section has no recognisable multi-column
layout, it keeps the normal extraction and records a `warning` (the flag is
never silently inert). Wrapped entries (a term that breaks across two printed
lines) are left as two adjacent bullets rather than guessing a join. Default
off; the kit template config does not set it. Enabled in the live pipeline for
`bolt-action-third-edition` and `necromunda-core-rulebook-2023`. See
`lib/index_layout.py` and `docs/extraction-manifest.md` (the `kind` field).

## Page ranges (page-level boundaries)

A section runs from its start page to `(next same-or-shallower entry's start) - 1`
(last section runs to the end). When two sections share a page the boundary is
approximate; the extractor records a `warning` and every note carries
`boundary: page-level`. This is an honest limitation, not a bug — do not claim
exact intra-page boundaries.

## Determinism

Scoped to "same PDF + pinned deps" (`templates/requirements.txt`). The `lib/`
helpers are pure; randomness or wall-clock values never enter the manifest
(`created` is the extraction date stored in the manifest).
