# Naming Contract (reference)

The authoritative spec is `docs/vault-contract.md`. This reference explains the
*why* and points at the code that implements each rule. Do not duplicate the
field list here.

## Where each rule lives in code

- **Slug** — `scripts/lib/slugify.py`. Pure: NFKD ASCII-fold, lowercase,
  collapse non-alphanumerics to `-`, trim, truncate, `section` fallback.
- **Positional ToC number** — `scripts/lib/toc_tree.py`. Derived from sibling
  order, not the title. Level jumps deeper than +1 are clamped so we never
  invent phantom parents. Per-group zero-padding widens past 99 siblings.
- **Paths** — `scripts/lib/naming.py` `compute_paths()`. Leaves sit in their
  parent branch's folder; branches are folder notes
  (`<num>-<slug>/<num>-<slug>.md`). Within-folder slug collisions get `-2`, `-3`.
- **Frontmatter** — `scripts/lib/frontmatter.py`. Deterministic key order and
  quoting.
- **Links** — `scripts/lib/links.py`. Aliased, vault-relative wikilinks;
  managed-region upsert for the library index.

## Why folder notes (not `index.md` everywhere)

Obsidian's default link resolution is "shortest path that's unique." If every
branch folder held an `index.md`, `[[index]]` would be ambiguous and links would
silently resolve to the wrong note. Naming each branch note after its folder
makes every basename unique, so even bare links would resolve — but we still use
full vault-relative aliased links for total stability. The only `index.md` is the
single library root, which is unique by definition.

## Why positional numbers

`get_toc()` gives no printed section number, and printed numbers are unreliable
(prefaces, appendices, inconsistent schemes). A positional number derived from
traversal order is always present, always sortable, and always matches reading
order — the backbone of "consistent structure and file naming."
