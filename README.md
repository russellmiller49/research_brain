# Research Memory

Research Memory is a private research-paper workspace with a local-first macOS app and a
synced web/mobile client. Its core job is intentionally narrow: recover a half-remembered
paper and open the exact passage that supports the match.

The production target is a closed beta for 20–50 biomedical researchers on Apple-silicon
Macs running macOS 13 or newer. The repository implements the beta architecture and release
pipeline; distribution still requires the project’s final bundle identifier, Apple signing
and notarization credentials, updater keys, and completion of the human/corpus acceptance
gates in [`docs/ACCEPTANCE_GATES.md`](docs/ACCEPTANCE_GATES.md).

## Beta capabilities

- Native Tauri 2 desktop shell with React, TypeScript, and an integrated PDF.js reader.
- Responsive web/mobile library with Supabase Auth, Storage, Realtime, and row-level
  account isolation.
- Cross-device papers, projects, annotations, import history, search, and private signed
  PDF access.
- Immutable, content-addressed managed PDF storage keyed by SHA-256.
- Safe folder/file import, native folder watching, and idempotent one-way Zotero import
  through Zotero’s read-only local API.
- Durable import, OCR, model-install, and reindex jobs with checkpoints, cancellation,
  retry, crash recovery, and actionable review states.
- Layout-aware PDFium extraction with page coordinates, reading-order recovery, repeated
  header/footer filtering, and per-page Tesseract OCR fallback.
- SQLite metadata and FTS5 retrieval plus a memory-mapped USearch HNSW semantic index using
  a pinned local `BAAI/bge-small-en-v1.5` ONNX model.
- Reciprocal-rank fusion across full text, semantics, metadata, numerical proximity,
  personal context, and notes, with observed-signal match explanations.
- Exact passage-to-page navigation, virtualized pages, thumbnails, outline, document find,
  keyboard controls, bookmarks, highlights, comments, and personal context.
- Markdown, RIS, BibTeX, XFDF, and newly generated annotated-PDF export. Originals are never
  modified.
- Numbered transactional migrations, pre-migration snapshots, encrypted portable backups,
  restore verification, 30-day app trash, redacted support bundles, and opt-in network
  metadata.
- A validated, versioned broad specialty and disease-family starter catalog with local
  profile persistence, deterministic personalized-tree generation, and typed read-only
  catalog APIs. Questionnaire and organization UI are not part of the current phase.
- Signed/notarized DMG and signed-update workflows, license policy checks, dependency
  audits, and CycloneDX SBOM generation.

Automated taxonomy suggestions, study cards, topic synthesis, Q&A, cloud AI, alerts,
collaboration, Windows, browser capture, and table/figure understanding are deliberately
outside this phase. Direct Google
Drive and OneDrive authorization and backup policy are scaffolded; remote file browsing
and the replication worker remain beta work.

## Architecture

```text
React + PDF.js webview
        │ typed Tauri commands only
        ▼
Rust desktop boundary
  ├─ native dialogs and folder watches
  ├─ sidecar lifecycle and crash cleanup
  ├─ private session credential
  ├─ save/export destinations
  └─ signed updates
        │ authenticated random loopback IPC
        ▼
Bundled Python core
  ├─ durable ingestion/OCR jobs
  ├─ PDFium geometry extraction
  ├─ metadata and conservative deduplication
  ├─ FTS5 + USearch retrieval
  └─ annotation/export/backup services
        │
        ├─ SQLite
        ├─ SHA-256 object store
        └─ versioned local indexes
```

The webview receives neither arbitrary filesystem access nor the Python session token. Rust
passes the token through the child environment, the Python process removes it after startup,
and all desktop API payloads reject unknown fields. PDF access uses short-lived opaque bearer
capabilities rather than exposing local paths.

See [`docs/TECHNICAL_ARCHITECTURE.md`](docs/TECHNICAL_ARCHITECTURE.md),
[`docs/DATA_MODEL.md`](docs/DATA_MODEL.md), and
[`docs/PRIVACY.md`](docs/PRIVACY.md). Taxonomy design, catalog provenance, and release
criteria are in [`docs/TAXONOMY_ARCHITECTURE.md`](docs/TAXONOMY_ARCHITECTURE.md),
[`docs/TAXONOMY_CATALOG.md`](docs/TAXONOMY_CATALOG.md), and
[`docs/TAXONOMY_ACCEPTANCE_GATES.md`](docs/TAXONOMY_ACCEPTANCE_GATES.md). The
repository-grounded security assessment and
tracked residual risks are in [`docs/SECURITY_REVIEW.md`](docs/SECURITY_REVIEW.md).

## Synced web beta

The Railway deployment is a static production build served by Caddy. Supabase remains the
managed backend for authentication, database row-level security, private PDF storage,
realtime changes, and Edge Functions. Railway variables are compiled into the Vite bundle:

```dotenv
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
VITE_MAC_DOWNLOAD_URL=https://github.com/russellmiller49/research_brain/releases
VITE_SOCIAL_AUTH_ENABLED=false
```

The root [`Dockerfile`](Dockerfile), [`Caddyfile`](Caddyfile), and
[`railway.json`](railway.json) are ready for GitHub-connected Railway deployments. The
container exposes `/healthz`, preserves SPA routing, and refuses to build without the two
Supabase client values. See [`docs/RAILWAY_DEPLOYMENT.md`](docs/RAILWAY_DEPLOYMENT.md) for
the production checklist.

## Development setup

Prerequisites:

- Apple-silicon macOS 13+
- Python 3.13 for development; CPython 3.12.13 for the signed sidecar
- Node.js 24 LTS
- Rust 1.97.1
- Tesseract 5

Bootstrap the pinned toolchain:

```bash
make bootstrap
```

Launch the native development app:

```bash
make desktop
```

Launch the synced local web stack:

```bash
npx --yes supabase@2.109.1 start
cd desktop
npm run dev:web
```

The default data location is the platform Application Support directory chosen by Tauri.
The unsupported v0.1 browser prototype is disabled by default and is available only for
migration/debugging with an explicit developer opt-in:

```bash
.venv-beta/bin/research-memory --legacy-web
```

Do not use that prototype as a beta deployment surface.

## Quality commands

```bash
make lint
make test
make licenses
make sbom
make benchmark-demo
```

The benchmark harness accepts JSONL records with a natural-language query and an expected
article identifier. A release-gating run requires at least 300 real queries:

```bash
.venv-beta/bin/python scripts/run_retrieval_benchmark.py \
  --data-dir /path/to/benchmark-library \
  --queries /path/to/queries.jsonl \
  --output artifacts/retrieval-report.json \
  --enforce
```

## Release build

The `Release macOS beta` GitHub Actions workflow assembles the pinned local model, bundles
and signs the Python and Tesseract sidecars, builds the arm64 app and DMG, notarizes the
artifact, verifies Gatekeeper/stapling/signatures, and uploads the update artifact, SBOM, and
license inventory. OCR is built from an explicit conda-forge `osx-arm64` lock whose package
URLs and SHA-256 values are checked against the license manifest; its dylib relocation tool
is also source- and checksum-pinned. The release verifier
inspects every Mach-O in the app and rejects a missing arm64 slice or a minimum deployment
target newer than macOS 13. The sidecar is resolved separately from
`requirements-release.lock` using macOS 13 arm64 wheel tags; its ONNX Runtime compatibility
constraint is documented in `packaging/macos-release-constraints.txt`.

Before invoking it, configure:

- a final non-placeholder reverse-DNS bundle identifier;
- Developer ID Application certificate and Apple notarization credentials;
- an HTTPS update endpoint;
- Tauri updater public/private signing keys.

The complete promotion checklist is in
[`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).

## Privacy and intended use

Core import, OCR, search, reading, annotation, and export work offline. Crossref/PubMed
enrichment is disabled until the user opts in and sends identifiers only. Diagnostics are
also opt-in and exclude PDF text, filenames, paths, searches, notes, and annotations.

Research Memory is for legally obtained published literature. It is not for PHI, clinical
records, autonomous recommendations, or validated systematic-review adjudication. Use the
macOS account boundary and FileVault; app-specific vault encryption is deferred.

The taxonomy seed organizes literature and is not clinically complete. It does not make
clinical recommendations. Automatic suggestions and automatic disease-state extraction are
disabled by default and remain subject to separate validation gates.

## License

MIT. Production PDF parsing uses permissively distributed PDFium bindings; PyMuPDF is not a
runtime dependency. The release pipeline rejects AGPL and GPL-3 dependencies and produces a
third-party license inventory and SBOM covering Python, Node, Rust, the OCR runtime, and the
offline model. Bundled notices, including the dynamically linked LGPL libiconv component,
are in
[`THIRD_PARTY_NOTICES.md`](desktop/src-tauri/resources/legal/THIRD_PARTY_NOTICES.md).
