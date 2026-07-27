# Beta Acceptance Gates

These are release blockers. CI passing alone does not satisfy the corpus, human, or
observation gates.

The taxonomy foundation has additional catalog, profile, classification, privacy,
accessibility, performance, and durability gates in
[`TAXONOMY_ACCEPTANCE_GATES.md`](TAXONOMY_ACCEPTANCE_GATES.md). Phase 1 test completion does
not authorize automatic suggestions, auto-apply, disease-state extraction, questionnaire
UI, or cloud taxonomy persistence.

## Retrieval quality

- At least 300 natural half-memory queries from five biomedical users.
- Hybrid top-5 retrieval at least 85%.
- Hybrid top-10 retrieval at least 95%.
- Top-5 at least 15 percentage points above the same corpus/query FTS-only baseline.
- Query set stratified across wording, semantic, numerical, methods, metadata, and personal
  context recall.

Use `scripts/run_retrieval_benchmark.py --enforce`; archive the JSON report with the release.

## Performance

On the named baseline Apple-silicon Mac and a representative 10,000-PDF/250,000-page corpus:

- warm-search p95 below 1.5 seconds;
- result-to-highlight p95 below 2 seconds;
- UI remains responsive during import, OCR, model install, and reindex.

Record hardware, OS, power mode, corpus composition, cold/warm procedure, and raw timings.

## Ingestion and provenance

- Acceptable human reading order on at least 95% of sampled born-digital pages.
- DOI/PMID precision at least 99%.
- Zero false automatic article merges.
- Every displayed snippet exists on its cited page.
- Every source highlight resolves to stored coordinates on the cited asset version.
- No structured study claim or topic synthesis appears in the beta UI.

The curated corpus must include clean/degraded scans, two-column, rotated, table-heavy,
corrupt, encrypted, oversized, missing, duplicate-version, and multi-article PDFs.

## Interoperability

- Highlights/comments round-trip through Preview, Acrobat, and PDF.js on the export corpus.
- RIS and BibTeX parse in Zotero.
- Zotero reimport is idempotent and preserves item, collection, attachment, and annotation
  relationships.

## Durability and recovery

- Crash the process during every ingestion stage; each job resumes exactly once.
- No duplicate article/file rows and no partial object-store files.
- Backup/restore verifies PDF hashes, row counts, annotations, collections, and a clean
  search-index rebuild.
- Delete/restore/purge preserves source files and honors the 30-day app-trash interval.
- Model-version change produces resumable reindexing with no mixed-version results.

## Release quality

- Python, React, Rust, migration, private-boundary, accessibility, license, dependency,
  SBOM, and signed-artifact checks pass in CI.
- Internal alpha completes before a five-user design-partner trial.
- No data-loss incident for two consecutive weeks.
- At least 99.5% crash-free beta sessions over the observation window.
- All unresolved Critical/High security findings are closed or accepted in writing.
- The taxonomy catalog has zero missing references/cycles, every credential pack resolves,
  and removed nodes preserve user assignments.
- `taxonomy_auto_apply_enabled` and
  `taxonomy_disease_state_extraction_enabled` remain false until their physician-reviewed,
  evidence-specific gates pass.
