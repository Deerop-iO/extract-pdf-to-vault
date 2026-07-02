# Vault Contract

This is the **single source of truth** for how a PDF becomes an Obsidian vault:
folder layout, file naming, frontmatter schema, and wikilink style.

Rules (`.cursor/rules/*.mdc`), references, and the verification harness
(`scripts/verify_vault.py`) all defer to this file. If any of them disagree with
this document, this document wins and the others are bugs.

Everything here is **deterministic**: the same input PDF plus the same pinned
dependency versions must always produce the same folder tree, the same file
names, and the same frontmatter. The harness asserts this.

---

## 1. Folder layout

One folder per source PDF. Nested folders mirror the PDF table-of-contents (ToC)
depth. One note per ToC leaf. Branch sections (ToC entries that have children)
get a **folder note** named after their own folder. A branch folder note may
also carry **preamble body** — the content on the pages a chapter owns before
its first bookmarked subsection — rendered above its Contents list (see §5).

```
<vault-output>/
  index.md                          # the ONE library index (MOC) for the whole vault
  <source-slug>/
    <source-slug>.md                # per-PDF MOC (folder note): metadata + full ToC
    01-introduction/
      01-introduction.md            # branch MOC (folder note)
      01.01-background.md           # leaf note
      01.02-scope.md                # leaf note
    02-methods/
      02-methods.md
      02.01-data-collection.md
    assets/                         # images/tables extracted from this PDF
      02.01-figure-1.png
  _templates/                       # optional Obsidian note templates (scaffolded once)
    note.md
    moc.md

<vault-output>/../.p2v/             # OUTSIDE the indexed vault tree
  <source-slug>.manifest.json       # raw extraction manifest = source of truth
  <source-slug>.generated.json      # list of paths this kit generated (safe-write)
```

Notes:

- The `.p2v/` directory lives **outside** the vault tree so Obsidian never
  surfaces `.json` files as notes. Default location is a sibling of the vault
  output folder.
- `assets/` is per-PDF, inside the PDF's own folder.
- `_templates/` is optional and only created by the "create default map" wizard
  step.

### 1.1 Layout modes (`layout` in `pipeline.config.json`)

The layout above is the default, `"nested"`. A second mode, `"uniform"`,
exists to satisfy one Obsidian constraint: **its file explorer always lists
folders before files within a folder, with no built-in option to interleave
them.** With `nested`, leaf chapters (files) therefore appear *below* branch
chapters (folders) in the explorer, even though their numeric prefixes are
correct — the reading order only holds inside the MOC notes.

- `"nested"` (default): branch sections are folder notes, leaf sections are
  plain files. Fewest folders; explorer order is folders-then-files.
- `"uniform"`: **every** section — leaf included — is its own folder note:

```
<source-slug>/
  01-introduction/
    01-introduction.md
    01.01-background/
      01.01-background.md          # leaf is now a folder note too
```

  Because every entry at every level is a folder, the explorer shows them in
  full ToC order (`01…NN`). Cost: one folder per section.

Both modes produce identical frontmatter, wikilinks, numbering, and pass the
same verification gates. Switching modes and rebuilding is safe: the builder
removes the previous run's now-orphaned paths (recorded in
`<source-slug>.generated.json`) and prunes the empty directories.

### 1.2 File Explorer sort spec (`sortspec.md`)

The recommended way to get reading order in the File Explorer while keeping the
clean `nested` layout is a `sortspec.md` note (not a change to the on-disk tree).
On build (when `sortspec` is true, the default) the builder scaffolds one
`sortspec.md` in the library root, **once**, and never overwrites it:

```yaml
---
sorting-spec: |-
  target-folder: <obsidian-root-relative library path>/*
  order-asc: a-z
---
```

- Its `sorting-spec` frontmatter is read by the community plugin **"Custom File
  Explorer sorting"** (`obsidian-custom-sort`). `order-asc: a-z` makes the plugin
  treat files and folders equally, so notes list in reading order (by numeric
  prefix) instead of Obsidian's default folders-before-files. It is **view-only**
  and requires the plugin to be installed to have any effect.
- `target-folder: <path>/*` scopes the rule to this library's own subtree, so it
  never reorders unrelated folders elsewhere in a larger Obsidian vault. When the
  vault is the Obsidian root (or not inside one), the target is `/*`.
- `sortspec.md` is **user-owned**, not a generated note: it carries no
  `generated_by: p2v`, is exempt from the naming contract (`verify_vault.py`
  skips non-generated notes in the filenames gate), and is never touched by
  orphan cleanup. User edits survive rebuilds.

---

## 2. File naming

### 2.1 Filename pattern

```
<toc-number>-<slug>.md
```

- `<toc-number>` is the **derived positional number** (see 2.2), zero-padded.
- `<slug>` is the deterministic slug of the ToC entry title (see 2.3).

Examples: `01-introduction.md`, `01.02-scope.md`, `02.01-data-collection.md`.

### 2.2 Derived ToC number (positional, NOT parsed from the title)

`get_toc()` returns `[level, title, start_page]` triples. It does **not** give a
printed section number. The ToC number is derived purely from **sibling
position** during a depth-first traversal:

- Top-level entries are numbered `01`, `02`, `03`, ... in order of appearance.
- A child's number is `<parent-number>.<child-index>`, e.g. the second child of
  `02` is `02.02`.
- Each numeric segment is zero-padded to **2 digits** by default
  (`pad_width` in `pipeline.config.json`). If any sibling group exceeds 99
  entries, padding for that group widens to fit (so sort order never breaks).
- Numbering is independent of any number printed in the title. A preface,
  foreword, or appendix with no printed number still gets a stable positional
  number.

This guarantees a stable, filesystem-sortable order that matches reading order.

### 2.3 Slug algorithm (pure function)

`slugify(title)` is a pure function applied to the ToC entry title:

1. Unicode NFKD normalize, then drop combining marks (ASCII-fold:
   `Résumé` -> `resume`).
2. Lowercase.
3. Replace any run of non-`[a-z0-9]` characters with a single `-`.
4. Strip leading/trailing `-`.
5. Truncate to `slug_max_len` (default 60) characters, then strip a trailing `-`.
6. If empty after all steps (e.g. a CJK-only title that ASCII-folds away), use
   `section`.
7. De-duplicate within the **same folder**: if a sibling already produced the
   same `<toc-number>-<slug>`, append `-2`, `-3`, ... Because the toc-number
   prefix is already unique per sibling, collisions only happen across different
   levels sharing a folder, which is rare; the suffix keeps it deterministic.

### 2.4 Folder names

A branch folder is named exactly like its branch note minus the `.md`:
`<toc-number>-<slug>/`. The folder note inside it repeats that name:
`<toc-number>-<slug>/<toc-number>-<slug>.md`.

### 2.5 Source slug

`<source-slug>` is `slugify()` applied to the PDF title (from PDF metadata
`title`, falling back to the file name without extension).

### 2.6 The one `index.md`

The only file named `index.md` in the whole vault is the single vault-root
library index. It is unique by definition, so it never collides. Every other MOC
is a folder note named after its folder. **Never** create a second `index.md`.

---

## 3. Frontmatter schema

Every generated note (leaf and folder-note MOC) carries YAML frontmatter with
exactly these keys, in this order:

```yaml
---
title: "1.2 Scope"                       # printed/display title (ToC number + title text)
source: "Designing Data-Intensive Apps.pdf"
source_pages: [12, 15]                   # [start, end], 1-based, inclusive
boundary: page-level                     # see §5; always "page-level" unless enriched
toc_level: 2                             # 1-based depth from get_toc()
toc_number: "01.02"                      # derived positional number (matches filename)
parent: "[[designing-data-intensive-apps/01-introduction/01-introduction|1 Introduction]]"
prev: "[[.../01.01-background|1.1 Background]]"   # omitted on the first leaf
next: "[[.../02-methods/02.01-data-collection|2.1 Data Collection]]"  # omitted on last leaf
tags: [pdf-import, designing-data-intensive-apps]
created: 2026-06-27                       # ISO date, the build date
generated_by: p2v                         # ownership marker for safe-write
---
```

Field rules:

- `source_pages` is always a 2-element list `[start, end]`.
- `parent` is omitted on the per-PDF MOC (it has no parent inside the PDF) but
  the per-PDF MOC instead links up to the library index via `parent`.
- `prev`/`next` walk the **ordered sequence of leaf notes** in reading order.
  Folder-note MOCs do not participate in the prev/next chain (they navigate via
  their child list), and so omit `prev`/`next`.
- `tags` always begins with `pdf-import` and the `<source-slug>`. Inferred topic
  tags (enriched tier only) are appended after these and never replace them.
- `generated_by: p2v` must be present on every generated file. Files without it
  are treated as user-authored and are never overwritten.

Unused optional fields are **omitted**, never set to `null` or empty.

### 3.1 Optional inferred keys (`enriched` tier)

The `/p2v-enrich-document` skill (post-build, agent-driven) may add these. They
are **inferred, labeled, and outside the determinism guarantee** (5, 7):

- `summary` — a faithful one-line condensation of the note's own body (never
  outside knowledge; fabrication ban). Rendered after `tags`. A string, or
  omitted. The frontmatter gate checks only that it is a string when present.
- `tags` — inferred `topic/*` tags plus an `enriched` marker are **appended**
  after `pdf-import` + the source slug, never replacing them. Topic tags come
  from a library-scoped controlled vocabulary (`topic-tags.json`), so they stay
  consistent across books.

They are written only through `scripts/apply_enrichment.py`, so key order and
quoting stay canonical (never hand-edited).

---

## 4. Wikilink style (fixed)

All internal links use **vault-relative paths with an alias**, never bare
basenames:

```
[[<source-slug>/<path>/<toc-number>-<slug>|<display title>]]
```

- The link target is the note path **relative to the vault root**, without the
  `.md` extension.
- The alias (after `|`) is the human display title.
- Bare links like `[[01.01-background]]` are **forbidden** — they depend on
  Obsidian's "shortest path" setting and break when basenames repeat. The
  harness fails the build if it finds a bare or unresolved internal link in a
  generated file.

### 4.1 The library-index link (the one cross-vault exception)

The per-PDF MOC's `parent` links to the library index. How that link is written
depends on where the vault lives (`library_index_link` in
`pipeline.config.json`):

- **`"auto"` (default):** if the vault output folder sits inside a larger
  Obsidian vault (a `.obsidian/` directory exists in an ancestor), the link is
  written as the **Obsidian-root-relative path** to the index, e.g.
  `[[Games/Bolt Action/Rules/Core rulebook/3/index|Imported PDFs]]`. This is
  required because a single Obsidian vault can hold **several** p2v libraries,
  each with its own `index.md`; a bare `[[index]]` would be ambiguous and
  Obsidian could resolve it to the wrong library (this is a real bug that has
  occurred).
- **Standalone output** (no `.obsidian/` ancestor) or `"root"`: the link is the
  bare `[[index|Imported PDFs]]`. With one index in the tree this is
  unambiguous, and it keeps standalone `../pdf-vault-output` builds unchanged.

This is the **only** place a target above the vault root may appear, and it is a
build-time decision (resolved from the `--vault` location); the manifest stays
location-independent so extraction remains deterministic. The on-disk file is
always `index.md` at the vault root regardless of how the link is spelled, and
the verifier recognizes both forms.

---

## 5. Fidelity and boundaries (honesty rules)

- `get_toc()` gives only the **start page** of each entry. A section's page
  range is `[start_page, next_sibling_or_ancestor_start - 1]`. The last section
  runs to the last page (or the end of its parent's range).
- A **branch** note's `source_pages` records this full span, but its rendered
  body shows only the **preamble** subset `[start_page, first_child_start - 1]`
  (the pages it owns before its first child); the remaining pages are reachable
  through the child notes it links in its Contents list. When a child begins on
  the branch's own start page there is no preamble and the branch note is a pure
  MOC. This is the only case where a note's body covers a subset of its
  `source_pages`, and it never drops or duplicates content.
- Because extraction is **page-level**, when two sections begin on the same page
  the boundary is approximate: the text of both may land in one note. Every note
  records `boundary: page-level` to make this explicit.
- The `clean` (default) tier never claims exact intra-page boundaries. The
  `enriched` tier may refine boundaries using in-page heading detection; when it
  does, it sets `boundary: heading-refined` and the refinement is labeled
  inferred in the build report.
- Never fabricate content that is not in the PDF. Summaries and topic tags exist
  only in the `enriched` tier and are clearly labeled inferred.

### 5.1 Body normalization (clean/enriched tiers)

PDFs leak recurring **artifacts** into the extracted markdown: running
headers, page-number footers, and DRM/ownership watermark lines. On the `clean`
(default) and `enriched` tiers the extractor removes them; the `structural` tier
keeps raw text. Two layers, both deterministic and conservative:

1. **Source-level (`header` / `footer` in `pipeline.config.json`)** — passed
   straight to `pymupdf4llm.to_markdown`. `footer: false` is the cleanest way
   to drop page numbers and running headers at the source. Both default to
   `true` (no behavior change); `footer: false` is opt-in because it can also
   drop legitimate footnotes on some PDFs.
2. **Body normalization (`boilerplate_patterns`, `strip_page_numbers`)** —
   applied per page after extraction:
   - `boilerplate_patterns`: regex list for **injected** boilerplate that is not
     header/footer furniture (e.g. a DRM line stamped mid-body and into table
     cells). A line that is only boilerplate is dropped; a fragment is excised in
     place, and its line is dropped only if excision left nothing but furniture
     (whitespace / `<br>` / a bare page number).
   - `strip_page_numbers`: drops **standalone** page-number *lines* (a whole line
     that is only a page number), bounded by the document's page count so a real
     number larger than the page count survives.

This removes only **provable** junk. Crucially, a table row is **never** deleted
on a numeric/empty heuristic: a single-cell numeric row may be a point-total
subtotal (`|||||504|`) and an all-empty row may be a blank character-sheet form
field. The only row removal is a row the excision step **emptied itself** (a
pure-boilerplate row). A table whose columns merely shifted is left intact and
**flagged by the verifier** (§7), never silently rewritten — fabricating a
"repaired" table would violate the fidelity rules above.

### 5.2 Guard-gated content repair (tier-neutral)

The deterministic pipeline never rewrites a shifted table (it flags it). The
`/p2v-repair-document` skill *may* repair such a table (or a glued index), but
only when a deterministic guard **proves the edit changed layout, not data**.
Because nothing is inferred, this is **tier-neutral**: a repaired note keeps its
current fidelity tier. Repairs are written through `scripts/apply_repair.py`
(safe-write + guard-clean by construction); enrichment defers structural fixes to
this skill.

- **Tables** — `scripts/verify_table.py --strict`
  (`lib.table_guard.data_drift_strict`): the data region's **token multiset** is
  preserved (no token added/dropped/changed) **and data rows are not reordered**
  (row swap). Permits boundary-only edits (row merge, column split, header
  promotion, name-wrap merge); rejects a row swap or any data change. (The looser
  multiset-only `data_drift` remains what the pipeline normalizers use.)
- **Index** — `scripts/verify_index.py` (`lib.index_guard.data_drift`): the
  **ordered word/page token sequence** across non-heading lines must be
  preserved. Permits de-gluing and letter-group re-heading; rejects a
  page-number swap between terms, or any add/drop. A true A-Z re-sort is *not*
  guard-verifiable and stays the job of the geometry-based `reconstruct_index`
  (§ per-source config), so the skill only de-glues where `reconstruct_index` is
  off.

An edit that fails its guard is refused and flagged for human review, never
applied. For `--kind table`, `apply_repair.py` additionally requires every
non-table line to be byte-identical old-vs-new, so prose outside a table can
never change. Source content is immutable unless the guard is clean.

---

## 6. Library index (`index.md`) managed region

The vault-root `index.md` is **co-owned**: the user may write freely, but a
managed block is owned by the kit:

```markdown
<!-- p2v:auto-start -->
- [[designing-data-intensive-apps/designing-data-intensive-apps|Designing Data-Intensive Applications]]
- [[some-other-book/some-other-book|Some Other Book]]
<!-- p2v:auto-end -->
```

`build_vault.py` only ever rewrites the lines between `p2v:auto-start` and
`p2v:auto-end`. Anything above or below is preserved verbatim. Each per-PDF
build registers (or updates) exactly one bullet linking to its per-PDF MOC,
sorted by `<source-slug>`.

The index file is always `index.md` at the vault root. When several libraries
share one Obsidian vault, each has its own `index.md` in its own subfolder, and
per-PDF MOCs link to *their* index via the qualified path described in §4.1.

---

## 7. Determinism guarantees (what the harness asserts)

Given the same input PDF and the same pinned dependency versions:

1. The set of generated file paths is identical across runs.
2. Each generated file's frontmatter and body are identical across runs (modulo
   `created`, which is pinned to the manifest's extraction date, not the wall
   clock at build time).
3. Every internal link resolves to an existing generated note (the library
   index is recognized in both its bare and qualified forms, §4.1).
4. Every asset referenced by a note exists on disk.
5. Every leaf note is reachable from the per-PDF MOC, and every per-PDF MOC is
   linked from the library index managed region.
6. **Tables are well-formed** (`tables` gate): every markdown table's data rows
   agree on column count. The gate flags only this inconsistency — it does not
   flag all-empty rows (blank form fields) or single-cell numeric rows
   (subtotals), which are legitimate.
7. **No configured boilerplate survives** (`boilerplate` gate): when
   `boilerplate_patterns` is set in `verify.config.json`, no note body matches
   any pattern. The gate is a no-op while the list is empty.

Gates are individually toggleable in `verify.config.json`; all default to on.

See [extraction-manifest.md](extraction-manifest.md) for the manifest schema
that feeds this contract.
