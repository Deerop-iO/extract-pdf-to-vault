# Extraction Manifest

The manifest is the **normalized, deterministic intermediate** between raw PDF
extraction and the vault. `extract.py` writes it; `build_vault.py` reads it.
Nothing downstream of the manifest ever re-opens the PDF.

This mirrors the figma-to-code kit's "normalized summary": it makes
*what the pipeline extracted* explicit and reviewable, separate from
*what gets written to the vault*.

File location: `.p2v/<source-slug>.manifest.json` (outside the indexed vault).

---

## Top-level shape

```json
{
  "schema_version": 1,
  "source": {
    "file_path": "/abs/path/to/book.pdf",
    "file_name": "book.pdf",
    "title": "Designing Data-Intensive Applications",
    "author": "Martin Kleppmann",
    "page_count": 590,
    "sha256": "…",                 // hash of the PDF bytes, for change detection
    "extracted_at": "2026-06-27"   // ISO date; becomes notes' `created`
  },
  "tooling": {
    "pymupdf": "1.24.10",
    "pymupdf4llm": "0.0.17"
  },
  "config": {
    "split_depth": 2,
    "pad_width": 2,
    "slug_max_len": 60,
    "tier": "clean",
    "header": true,                // passed to pymupdf4llm.to_markdown
    "footer": true,                // false drops page numbers / running headers at the source
    "strip_page_numbers": true,    // body normalization (clean/enriched only)
    "boilerplate_patterns": [],    // regex list, e.g. a DRM watermark
    "reformat_stat_blocks": false, // opt-in: Necromunda fighter + vehicle stat profiles -> tables
    "merge_wrapped_table_rows": false, // opt-in: fold wrapped Traits continuation rows in weapon charts
    "restore_ligatures": true,     // on by default: restore zero-width ligature glyphs dropped in table cells
    "promote_header_below_separator": false, // opt-in: fix a weapon-chart header pushed below the separator (group-row|sep|label-row)
    "collapse_table_headers": false,   // opt-in: fold a two-row (group+sub) weapon-chart header into one
    "split_am_traits": false,          // opt-in: split a fused `Am Traits` column into separate Am/Traits columns
    "merge_wrapped_name_rows": false,  // opt-in: fold an orphan weapon-name continuation row into the name above
    "guard_table_data": true       // on by default: hard-fail if a structural rule changes any table DATA token
  },
  "toc_present": true,
  "toc_source": "embedded",        // "embedded" | "toc-page" | "headings" | "pages" | "ignored"
  "sections": [ /* see below */ ],
  "warnings": [
    "Sections 1.1 and 1.2 share page 12; boundary is page-level."
  ]
}
```

- `sha256` lets `/p2v-refresh-document` detect whether the PDF actually changed.
- `tooling` records pinned versions so determinism claims are scoped correctly.
- `toc_source` records how the hierarchy was derived (see §3 of the contract and
  the no-ToC fallback below).

---

## Section node

`sections` is a flat, ordered list (depth-first, reading order). Hierarchy is
expressed via `toc_number` and `parent_number`, not nesting, so the list is easy
to diff.

```json
{
  "toc_number": "01.02",          // derived positional number (contract §2.2)
  "parent_number": "01",          // null for top-level
  "level": 2,                     // 1-based
  "title": "Scope",               // raw ToC title text
  "display_title": "1.2 Scope",   // number + title for `title` frontmatter/alias
  "slug": "scope",                // contract §2.3
  "is_leaf": true,                // false => folder note (branch)
  "start_page": 12,               // 1-based
  "end_page": 15,                 // 1-based inclusive; derived from next sibling/ancestor
  "markdown": "## Scope\n\nBody…", // page-level markdown (leaf: full range; branch: preamble)
  "assets": [
    { "ref": "02.01-figure-1.png", "page": 13, "kind": "image" }
  ]
}
```

Rules:

- A **leaf** carries `markdown` for its full `[start_page, end_page]` range.
- A **branch** (`is_leaf: false`) carries `markdown`/`assets` **only for its
  preamble** — the pages `[start_page, first_child_start - 1]` it owns before its
  first child (a chapter intro / body that sits above the chapter's first
  bookmarked subsection). When a child begins on the branch's own start page
  there is no preamble and the keys are omitted; the branch note is then a pure
  MOC generated from its children. Either way the branch note always renders its
  Contents list; preamble body, when present, appears above it. Preamble pages
  never overlap a child's pages, so content is captured exactly once.
- `markdown` is the concatenation of pymupdf4llm page chunks across the owned
  range, already in markdown. On the `clean`/`enriched`
  tiers each page is run through body normalization (contract §5.1) before it
  lands here: configured boilerplate is stripped and standalone page-number
  *lines* are dropped. Table rows are never removed on a numeric/empty heuristic
  (subtotals and blank form rows are kept). The `structural` tier stores raw
  text. `header`/`footer` are applied earlier, at the `to_markdown` call, on
  every tier.
- `assets[].ref` is the **final asset filename** (already renamed per contract),
  relative to the PDF's `assets/` folder.
- The list is the single ordering authority: `prev`/`next` leaf chaining and MOC
  child lists are both derived from traversing `sections` in order.
- `kind` (optional) tags a section's content shape. Currently the only value is
  `"index"`, set when `reconstruct_index` rebuilt a back-of-book alphabetical
  index from column geometry (one entry per line, true A–Z order, dotted leaders
  stripped). Its `markdown` carries plain page numbers; `build_vault` turns each
  into a wikilink to the note covering that page (with a heading anchor when the
  entry term matches a heading in that note). Sections without the key build
  normally.

---

## No-ToC fallback (`toc_source`)

### Source precedence

1. **`embedded`** — `doc.get_toc()` returned entries and `--ignore-toc` was not
   set. Always the default and preferred source. A `--fallback` flag passed at
   the same time is ignored with a one-line notice; pass `--ignore-toc` to
   override. If the embedded ToC looks degenerate (≥ half of titles are bare
   page numbers, or every entry is level 1 with numeric-only titles), a console
   warning is emitted suggesting `--ignore-toc --fallback toc` — but the
   embedded ToC is still used unless the user opts out.
2. **`ignored`** — `doc.get_toc()` was non-empty but `--ignore-toc` was passed.
   The embedded outline is dropped; the `--fallback` choice applies as if there
   were no embedded ToC.
3. **`toc-page`** — (`--ignore-toc --fallback toc`, or no embedded ToC and
   `--fallback toc`) Parse the document's own printed table-of-contents page(s).
   The ToC start page is found by matching `toc_title_pattern` (config, regex,
   case-insensitive; default covers common English and European headings:
   *contents, table of contents, toc, index, inhoudstafel, inhoudspgave,
   inhaltsverzeichnis, table des matières, índice, contenido*) against page
   headings. `--toc-page N` pins the start page explicitly, skipping detection.
   Hierarchy is inferred in `toc_hierarchy_mode` (`auto` by default):
   - `indent` — clusters each row's left-margin `x0` into bands; leftmost = L1.
   - `numbered` — strips outline prefixes (`"1.2 Methods"` → level 2, `"Methods"`).
   - `auto` — picks `numbered` when ≥ 60 % of rows have a prefix, else `indent`.
   Printed page numbers are mapped to physical pages via auto-detected offset
   (`physical = printed + offset`, derived by matching a sample of ToC titles
   against headings in the per-page markdown). Extraction hard-stops (never
   silently flattens) if no usable structure is found on the ToC page.
   **Inferred, not extracted** — flagged in `warnings`; labeled in the manifest.
   Offset caveats: if fewer than two sample titles match page headings, offset
   defaults to 0 with a warning; if the modal offset is inconsistent, a warning
   is emitted but the modal is used. Check these warnings when `start_page`
   values look wrong.
4. **`headings`** — No embedded ToC (or `--ignore-toc`); `--fallback headings`.
   Flat, single-level (every entry is `level: 1`; one entry per page; first
   heading wins; raw `#`/`##` depth discarded). Inferred, not extracted.
5. **`pages`** — No embedded ToC (or `--ignore-toc`); `--fallback pages`. One
   note per page (`level: 1`, titles like `Page 13`). Inferred.

The pipeline never silently invents a hierarchy: if `get_toc()` is empty it
stops and the workflow asks the user which fallback to use.

Note on `toc_present`: it stays `true` for `toc-page`, `headings`, and `pages`
fallbacks (a synthetic hierarchy exists). `toc_source` is the discriminator.

---

## Scanned-PDF guard

If total extracted text length across all pages is below `min_text_chars`
(config, default 200) the manifest is **not** written for vault building.
Instead `extract.py` exits with a clear "looks scanned / image-only; OCR is
opt-in" message. OCR is enabled only via an explicit config flag.
