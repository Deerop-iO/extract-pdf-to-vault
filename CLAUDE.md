# Agent Charter — pdf-to-vault kit

You are operating the **pdf-to-vault agent kit**. Your job is to turn PDFs into
a structured Obsidian markdown vault that is easy for both humans and AI to
navigate.

Core discipline:

- The extraction pipeline (`scripts/extract.py`, PyMuPDF + pymupdf4llm) is the
  **source of truth**. Never fabricate content, sections, or structure the PDF
  does not contain.
- A Docker image is available as a no-Python-install alternative (`docker build -t p2v .`); see `DOCKER.md`.
- Everything about folder layout, file naming, frontmatter, and wikilinks is
  defined once in [`docs/vault-contract.md`](docs/vault-contract.md). Follow it
  exactly; the verification harness enforces it.
- Separate three layers in every substantive response: **Extracted** (what the
  pipeline returned), **Inferred** (split depth, slugs, tags, summaries), and
  **Output** (the vault files written).
- Write into the sibling vault output folder, never into this kit.

Start here:

- New setup -> `/p2v-start-project`
- Convert one PDF -> `/p2v-build-document`
- Check an existing vault -> `/p2v-verify-vault`

Read [`.cursor/skills/pdf-to-vault-agent/SKILL.md`](.cursor/skills/pdf-to-vault-agent/SKILL.md)
for the full operating contract.
