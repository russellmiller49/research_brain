# Technical Architecture

## System boundary

Research Memory 0.2 is a Tauri 2 desktop application, not a browser-hosted product.

```text
┌───────────────────────────────────────────────────────────┐
│ Tauri application                                        │
│                                                           │
│  React/TypeScript + PDF.js                                │
│      │ invoke typed commands                              │
│      ▼                                                    │
│  Rust trust boundary                                      │
│  dialogs │ watchers │ sidecar │ exports │ updates         │
└──────────────────────┬────────────────────────────────────┘
                       │ random loopback port
                       │ per-launch authenticated IPC
                       ▼
┌───────────────────────────────────────────────────────────┐
│ Bundled Python sidecar                                    │
│ jobs │ extraction │ OCR │ metadata │ retrieval │ export   │
└─────────────┬──────────────────────────┬───────────────────┘
              │                          │
              ▼                          ▼
  SQLite + FTS5 + job state     objects/ + indexes/
```

Rust chooses an unused loopback port, creates a high-entropy session token, passes it to the
sidecar through the child environment, and proxies a fixed command set. Python removes the
environment value after configuration is loaded so OCR/model child processes cannot inherit
it. The webview does not receive the token or raw paths and has only the minimal Tauri core
capability.

## Storage

Imported PDFs are copied atomically into a content-addressed object store:

```text
objects/<sha256[0:2]>/<sha256[2:4]>/<sha256>.pdf
```

Each copy is written to a private temporary file, flushed and synced, verified by SHA-256,
atomically renamed, and made read-only to normal app flows. Source path, source kind,
filename, role, version, availability, and primary status are separate database fields.
Exact bytes are deduplicated while article/version decisions remain explicit.

SQLite owns bibliographic data, file relationships, layout blocks, passages, annotations,
projects, import cursors, durable jobs, review decisions, and application settings. WAL,
foreign keys, busy timeouts, and short transactions allow workers and the UI to coexist.

Numbered migrations run transactionally. Before any pending migration, SQLite’s backup API
creates a pre-migration snapshot. The v0.1 migration keeps bibliographic records, notes,
projects, and file relationships but invalidates all derived page text, passages, keywords,
study claims, and vectors for rebuild.

## Ingestion pipeline

Jobs move through stable stages and persist input, progress, checkpoint, output, redacted
error code, retryability, cancellation request, and timestamps.

```text
discover → hash/copy → inspect → extract/OCR → metadata
         → reconcile/review → chunk → embed → publish indexes
```

The manager recovers `running` jobs as queued after a crash. Folder jobs save the last
completed canonical path and resume after it. Outputs use idempotent database keys and
atomic object writes.

PDFium returns page dimensions and text rectangles. An XY-cut ordering pass reconstructs
columns; recurrent marginal text is removed as headers/footers. Sparse/image pages are
rasterized and sent to a bounded Tesseract process, and TSV coordinates are converted back
to PDF points. Passages retain source bounding boxes clipped to visible page bounds.

Malformed, encrypted, over-limit, partially readable, scanned, missing, and suspected
multi-article files remain visible review states. Passwords live only in the in-memory job
manager for the current session.

## Metadata and identity

First-page DOI/PMID extraction is deliberately conservative. Only an exact SHA-256 match or
matching DOI/PMID may merge automatically. Normalized-title matches generate a probable
duplicate review. Conflicting local, user, or online metadata is stored with evidence and
requires a decision. Review outcomes are audit rows.

Zotero import calls only `http://127.0.0.1:23119/api`, streams attachment bytes with size
limits, preserves item keys/versions/collections/attachment relationships/annotations, and
copies PDFs into managed storage. Reimport uses external keys and payload hashes for
idempotency. Zotero’s SQLite database is never read.

Crossref/PubMed enrichment is disabled by default and gated by a persisted consent setting.
Only detected identifiers are submitted.

## Retrieval

Each page becomes coordinate-bearing passages. SQLite FTS5 provides lexical candidates.
FastEmbed runs a pinned quantized `BAAI/bge-small-en-v1.5` ONNX model locally, and USearch
stores the HNSW index in a memory-mapped file.

Every passage records its index version, embedding backend, and model. A mismatch marks the
index stale and queues resumable reindex work rather than mixing vector spaces.

Search uses reciprocal-rank fusion across:

- FTS5 passages;
- semantic nearest neighbors;
- title/author/journal/identifier metadata;
- numerical-token proximity;
- `why saved`, user summary, and notes.

Results are article-deduplicated and return only observed match-reason codes. Rank is an
ordering, not a fabricated percentage.

## Reader and annotation model

PDF.js renders the short-lived asset capability URL. Pages and thumbnails render only near
the viewport and release canvases when distant. PDF.js’s text layer preserves selection and
rotation. Search bounding boxes and annotation quads are projected from PDF points into the
current viewport.

Annotations remain in SQLite and refer to an immutable asset version. Exports create new
files. Annotated PDF export uses `pypdf`; XFDF preserves interoperable quad points; Markdown,
RIS, and BibTeX cover note and citation portability.

## Backup, deletion, and recovery

Portable backups use Scrypt-derived AES-256-GCM encryption and include a manifest, SQLite
backup, and managed objects. Restore verifies authentication, manifest paths, object hashes,
and row/object integrity and snapshots the current database first. Search indexes are
rebuildable and are not trusted as the source of truth.

Deletion is a soft delete with 30-day retention. Purging removes only app-managed objects
that have no remaining live references; source files are never touched.

## Release and operations

The release workflow targets arm64 macOS 13+, bundles the PyInstaller core, relocatable
Tesseract and language data, and the pinned offline model. Tesseract 5.5.2 and its native
dependencies come from a SHA-256-locked conda-forge `osx-arm64` environment rather than the
build host. An artifact check inspects every Mach-O slice and deployment target before
Gatekeeper checks. The workflow applies hardened-runtime signatures, builds/notarizes a DMG,
generates signed updater artifacts, and verifies codesign, Gatekeeper, stapling, mounted-app
identity, license policy, and SBOM output.

The Python release sidecar uses CPython 3.12.13 and a separate fully hashed lock. Wheels are
resolved for `macosx_13_0_arm64`, every installed Mach-O is checked before freezing, and the
same clean environment drives the release license inventory and complete SBOM. ONNX Runtime
is constrained to 1.19.2 because later arm64 binaries require a newer macOS 13 point release
than the beta's 13.0 floor.

CI covers Python 3.11/3.12/3.13, React build and accessibility smoke test, Rust
formatting/clippy/tests, migrations, private-IPC behavior, damaged/encrypted/columnar PDFs,
job recovery, retrieval provenance, dependency audits, licenses, and CycloneDX SBOM
generation.

Known residual risks and mitigations are tracked in
[`SECURITY_REVIEW.md`](SECURITY_REVIEW.md).
