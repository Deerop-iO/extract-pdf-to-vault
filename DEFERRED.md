# Deferred (out of scope for Phase 1)

> Detailed rationale and current status for each item: see [BACKLOG.md](BACKLOG.md).

Phase 1 is a deterministic, faithful PDF -> vault pipeline. The following are
intentionally deferred to keep it small and trustworthy.

- **Enriched tier** — LLM-generated per-note summaries, inferred topic tags, and
  intra-page boundary refinement via heading detection. (`tier: enriched`.)
- **OCR for scanned PDFs** — opt-in `ocrmypdf` pass before extraction. Phase 1
  detects scanned PDFs and stops with guidance instead.
- **Tables as structured data** — Phase 1 keeps pymupdf4llm's inline markdown
  tables; extracting them to CSV/embeds is deferred.
- **More workflows** — `/p2v-extract-pdf`, `/p2v-build-note`,
  `/p2v-build-library`, `/p2v-refresh-document`, `/p2v-improve-kit`.
- **Dropping into an existing populated vault subtree** beyond the safe-write
  ownership model already implemented.
