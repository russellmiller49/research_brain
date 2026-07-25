# Technical Architecture

## 1. Current architecture

Research Memory v0.1 is a single-user local application:

```text
Browser
  │
  │ HTTP on 127.0.0.1
  ▼
FastAPI + server-rendered Jinja UI
  ├── Ingestion service
  ├── Metadata service
  ├── Study-clue extractor
  ├── Hybrid search service
  ├── Source-grounded Q&A service
  └── Export service
          │
          ▼
SQLite + FTS5
  ├── bibliographic records
  ├── article/file-version relationships
  ├── page text
  ├── passage chunks
  ├── vector blobs
  ├── notes
  └── projects
          │
          ▼
Local PDF files or managed private copies
```

The browser is a UI client only. The FastAPI process performs filesystem access, PDF extraction, indexing, and retrieval.

## 2. Why this architecture was selected

- It is immediately runnable on macOS and Windows without a separate database server.
- SQLite FTS5 provides reliable local full-text search.
- Page and chunk tables make source provenance explicit.
- Server-rendered HTML keeps the first release small and auditable.
- The service boundaries can later be exposed to a Tauri, React, or mobile client.
- The article/file separation supports preprints, accepted manuscripts, publisher versions, and supplements.

## 3. Retrieval pipeline

### Indexing

1. Compute file SHA-256.
2. Detect an exact file match.
3. Extract page text with PyMuPDF.
4. Infer and optionally enrich metadata.
5. Detect a probable intellectual-work match by DOI or normalized title.
6. Preserve page text.
7. Split each page into overlapping passages.
8. Insert passages into FTS5.
9. Compute and persist local vectors.
10. Generate conservative keyword and study-clue records.

### Querying

1. Convert natural language into a safe, forgiving FTS5 expression.
2. Retrieve lexical passage candidates.
3. Compute query-vector similarity against the in-memory persisted vector matrix.
4. Match title, authors, abstract, why-saved text, summary, and notes.
5. Apply scope filters.
6. Combine signals at the passage level.
7. Select the strongest passage for each document.
8. Add a small explicit importance boost.
9. Return the source page and the signals that produced the match.

The baseline vector index uses hashed word and bigram features. A sentence-transformer implementation satisfies the same interface.

## 4. Provenance model

Every passage stores:

- `document_id`
- `page_number`
- `chunk_index`
- passage text
- embedding backend and dimension

Structured study fields currently store a page and confidence in JSON. The next schema should normalize these into an `extractions` table with evidence spans, verification status, editor, timestamps, and history.

## 5. Recommended next schema changes

```text
jobs
  id, type, status, progress, input, error, created_at, updated_at

extractions
  id, document_id, schema_name, field_name, value_json,
  page_number, start_offset, end_offset, evidence_text,
  method, confidence, verification_state, created_at, updated_at

extraction_revisions
  id, extraction_id, prior_value_json, new_value_json,
  editor_id, reason, created_at

citations
  citing_document_id, cited_identifier, cited_document_id,
  raw_reference, confidence

document_relationships
  source_document_id, target_document_id, relationship_type,
  confidence, evidence_json, verification_state

figures
  id, document_id, page_number, figure_number, caption,
  image_path, extracted_labels_json, embedding

tables
  id, document_id, page_number, table_number, caption,
  structured_data_json, extraction_confidence
```

## 6. Background processing

The synchronous ingestion path is appropriate for an MVP but should be replaced with a durable job queue before large-scale deployment.

A local-first production design can use:

- SQLite job table
- A bounded worker pool
- Per-stage checkpoints
- Idempotent task keys
- Cancellation and pause
- CPU, memory, and battery-aware limits
- Resumable OCR and embeddings

A remote multiuser version should move jobs to a managed queue and isolate untrusted document parsing.

## 7. Desktop transition

The least disruptive desktop path is:

1. Preserve FastAPI as the local application service.
2. Add a Tauri shell for native windows, folder dialogs, system tray, and filesystem watching.
3. Start the Python sidecar on a random loopback port.
4. Store an ephemeral authentication token in memory and require it on every request.
5. Bundle the Python runtime and dependencies.
6. Sign and notarize platform installers.

A later rewrite could move the local service into Rust, but that is not necessary to validate product-market fit.

## 8. Security hardening roadmap

- Random per-session local API token
- Strict host validation and CORS policy
- Content Security Policy without remote scripts
- Sandboxed PDF parsing process
- Encrypted database and managed files
- Operating-system credential store for API secrets
- Explicit model-provider allowlist
- Per-project data-export controls
- Backup encryption and recovery testing
- Signed updates
- Dependency and SBOM scanning

## 9. Scale considerations

For approximately 1,000 conventional articles, SQLite and an in-memory vector matrix are reasonable. At larger scale:

- Persist an HNSW or similar approximate-nearest-neighbor index.
- Store vector-index version and tombstones.
- Incrementally update rather than reload the complete matrix.
- Separate page text from the transactional database when corpus size requires it.
- Cache query results and topic aggregations.
- Use incremental citation and relationship extraction.

Search quality should be benchmarked before changing the index solely for performance.

## 10. Testing strategy

Current automated tests cover:

- PDF ingestion
- Exact duplicate detection
- Alternate-version attachment
- Metadata extraction
- Full-text and approximate retrieval
- Personal-context matching
- Page-provenance Q&A
- Principal web routes

Next tests should include:

- Corrupted, encrypted, scanned, unusually large, and malformed PDFs
- Multicolumn extraction quality
- Metadata conflicts between local text and Crossref
- Reindexing and interrupted jobs
- Retrieval benchmarks with expert half-memory queries
- Browser UI tests
- Export round trips
- Migration tests
- Security boundary tests
