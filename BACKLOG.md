# Backlog

Forward roadmap. Pull items into a Phase when picked up; move shipped items to
`CHANGELOG.md`.

## Phase 2 — enrichment & coverage
- `tier: enriched` summaries + `topic/*` tags — SHIPPED as the
  `/p2v-enrich-document` skill (see `CHANGELOG.md`). Remaining here: only
  **heading-refined boundaries** (`boundary: heading-refined`) — refine
  page-level section boundaries using in-page heading detection, labeled
  inferred.
- Opt-in OCR pipeline (`ocrmypdf`) for scanned PDFs.
  - WHY parked: a larger, higher-risk feature for *coverage* of scanned/image-
    only PDFs, not a fidelity fix for PDFs that already extract. OCR stays
    explicitly opt-in (never automatic) per the extraction rules.
- Workflows: `/p2v-extract-pdf`, `/p2v-build-note`, `/p2v-build-library`,
  `/p2v-refresh-document` (diff + confirm), `/p2v-improve-kit`.
- References: `toc-parsing.md`, `structuring.md`, `frontmatter-schema.md`,
  `linking.md`, `assets-and-tables.md`, `ocr-and-scanned.md`,
  `batch-extraction.md`, `common-issues.md`.
- Docs: `frontmatter-schema.md`, `naming-conventions.md`, `toc-mapping.md`,
  `pipeline.md`, `principles.md`, `evals.md`, `explainer.md`.

## Quality
- Determinism gate in `verify_vault.py` (rebuild from manifest into a temp dir
  and diff owned files).
  - WHY: the vault contract promises determinism (same manifest -> same paths
    and bytes) but nothing *enforces* it; a rebuild-and-diff turns the claim
    into a gate. Currently covered only by `tests/` and a manual double-build.
- Table-to-structured-data extraction.
  - WHY: turn detected tables into parsed/queryable data (e.g. Dataview-ready
    stat blocks). The `table_strategy` config knob (shipped) is the lightweight
    *detection-side* first step -- `"text"` recovers stat blocks that render as
    spaced text -- but true structured output (typed columns) is still open.
- Dataview-friendly frontmatter conventions (status, read progress).

## Nice to have
- A `/p2v-build-library` overview dashboard note with Dataview queries.
- Cross-document `[[ ]]` linking by shared tags/topics (enriched).
- Docker functionality: a container image (pinned `templates/requirements.txt`
  + PyMuPDF/pymupdf4llm) so `extract.py`/`build_vault.py`/`verify_vault.py` run
  without a local venv setup.
  - WHY: determinism today is scoped to "same input PDF + pinned dependency
    versions," which still depends on the operator's local Python/venv matching
    those pins. A container removes that variable and makes the pipeline
    portable across machines (e.g. running the kit on a different host or in
    CI) without changing anything about the extraction/build/verify contract.

## Maybe (surfaced by improve-plan)
Candidates raised during a kit review; parked here with rationale, not yet
committed to a Phase.
- Durable residual heading-artifact fix: a per-source literal `replacements`
  list on the `sources` map, applied heading-scoped at extract time.
  - WHY: the spaced-caps fix collapses only the unambiguous *fully-spaced* class
    (`C H A P T E R` -> `CHAPTER`). Partial kerning residue (`T WO`, `F URY`)
    cannot be auto-corrected safely, because a regex can't distinguish it from
    legitimate text (`(A OR B)`, `A NEW ERA`). A manual vault edit is overwritten
    on the next rebuild, so the durable fix is deterministic, *user-supplied*
    per-source replacements -- explicit strings, no inference.
- Thin orchestrator: one command running extract -> build -> verify per source.
  - WHY: today these are three manual commands run in sequence; the new
    end-to-end smoke test already proves the chain is sound. An orchestrator
    reduces operator error and makes re-runs/refreshes trivial.
- Follow-ups to `--fallback headings` (shipped flat, one-entry-per-page):
  - Multi-level nesting from heading sizes/levels.
    - WHY parked: the layout classifier's `#`/`##` depth proved unreliable in
      testing (a real 343-page rulebook emitted only `section-header`s, no
      titles), and naive pass-through nests everything under the first heading.
      Reliable nesting needs a font-geometry level model, which is larger scope.
  - Config-driven default fallback (a `sources`/global key) so a refresh needn't
    re-pass `--fallback headings` each run.
    - WHY parked: refresh/orchestrator workflows aren't shipped yet; until then
      the explicit CLI flag keeps the choice opt-in and visible.
