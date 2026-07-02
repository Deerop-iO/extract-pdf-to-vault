---
name: pdf-to-vault-agent
description: Extracts PDFs into a structured Obsidian markdown vault via a deterministic PyMuPDF + pymupdf4llm pipeline, driven by the PDF table of contents, with consistent folder structure, file naming, frontmatter, and wikilinks. Use when converting a PDF (book, report, spec, deck) into navigable notes for humans and AI, setting up a PDF-to-vault pipeline, or verifying a generated vault's consistency.
---

# pdf-to-vault Agent

## Workflow Skills (router)

Step-by-step procedures live in user-triggerable workflow skills under
`workflows/` (each `disable-model-invocation: true`, never auto-loaded). When a
request matches one of these shapes, **read and follow the named file** before
acting. This skill owns the cross-cutting discipline; each workflow owns its own
preconditions and steps.

| Request shape | Read and follow | User trigger |
|---|---|---|
| New project / setup wizard (vault path, deps, default map) | `workflows/p2v-start-project/SKILL.md` | `/p2v-start-project` |
| Convert one PDF into a nested vault tree + MOC | `workflows/p2v-build-document/SKILL.md` | `/p2v-build-document` |
| Verify an existing vault's consistency | `workflows/p2v-verify-vault/SKILL.md` | `/p2v-verify-vault` |
| Enrich a built vault (summary + topic tags) | `workflows/p2v-enrich-document/SKILL.md` | `/p2v-enrich-document` |
| Repair malformed tables / glued index in a built vault (guard-gated, tier-neutral) | `workflows/p2v-repair-document/SKILL.md` | `/p2v-repair-document` |

For a brand-new setup, start with `workflows/p2v-start-project/SKILL.md`. Use the
AskQuestion tool for the multiple-choice setup steps so the user sees clickable
options.

The `enriched` tier ships as the post-build `/p2v-enrich-document` skill (summary
+ controlled topic tags); see [references/enrichment.md](references/enrichment.md).
Structural repair of malformed tables / glued index is the separate, tier-neutral
`/p2v-repair-document` skill (guard-gated, layout-only); see
[references/repair.md](references/repair.md). Other Phase 2 workflows
(extract-only, single-note, multi-PDF library, refresh, improve-kit) are on the
backlog; see `BACKLOG.md`.

## Default output shape

Respond in this order:

1. `Scope` — PDF(s), page range, split depth, vault path.
2. `Extraction` — manifest summary: ToC source, section/leaf counts, warnings.
3. `Structuring` — split depth, slugs, file/folder plan, frontmatter, link graph.
4. `Output` — files written into the sibling vault, with paths.
5. `Gotchas` — boundary limits, fallbacks used, fidelity tier, next step.

## Three layers in every response

- **Extracted** — what the pipeline returned (the manifest is the source of truth).
- **Inferred** — split depth, slugs, tags, summaries, link graph.
- **Output** — the vault files.

Keep them visibly separate.

## The contract

`docs/vault-contract.md` is the single source of truth for folder layout, file
naming, frontmatter, and wikilink style. `scripts/verify_vault.py` enforces it.
Never restate it ad hoc; follow it.

## Fidelity tiers

Name the tier every time: `structural`, `clean` (default), or `enriched`
(inferred summaries/tags via the `/p2v-enrich-document` skill; heading-refined
boundaries remain Phase 2).

## Guardrails

- The Python pipeline is the only extraction source. Do not fabricate.
- Section boundaries are page-level; say so.
- No embedded ToC -> report and use a declared fallback, never guess a hierarchy.
- Scanned PDF -> stop; OCR is opt-in.
- Write into the sibling vault, never the kit. Respect the safe-write model.

## Changelog

After a task that notably changes this kit, update `CHANGELOG.md` under
`## [Unreleased]`.

## References

- [Extraction](references/extraction.md)
- [Naming Contract](references/naming-contract.md)
- [Verification Harness](references/verification-harness.md)
