# Research Memory Security Review

Review date: 2026-07-25
Scope: macOS Tauri shell, React renderer, authenticated Python sidecar, PDF/OCR
ingestion, managed storage, backups, updates, Zotero import, and release automation.

## Outcome

No Critical or High application finding remains open for the controlled 20–50-person
macOS beta. One Python dependency advisory and three Rust transitive advisories were
found during this review and remediated in the pinned lockfiles. The residual
findings below are appropriate to track for the closed beta, but the two P2 findings
should be closed before broad public distribution.

## Findings

### 1. [P2] Untrusted PDF parsing is not isolated from the library process

**Evidence.** User-selected PDFs are opened by PDFium in
`src/research_memory/services/metadata.py:303`, and rasterized page data is passed to
Tesseract beginning at `src/research_memory/services/metadata.py:188`. Both execute from
the Python sidecar launched at `desktop/src-tauri/src/lib.rs:1038`. The direct-download
build uses hardened runtime but is not an App Sandbox build
(`desktop/src-tauri/Entitlements.plist:4-9`).

**Impact.** A memory-safety flaw in a native PDF/OCR dependency could expose or alter
the user's library with the privileges of the signed application.

**Current controls.** Imports are copied into immutable content-addressed storage;
PDF size, page count, rendered-pixel count, worker concurrency, and OCR time are
bounded; the sidecar token is removed from child-process environments; dependencies
are pinned and scanned.

**Recommendation.** Before public distribution, move PDFium and Tesseract into a
separate restricted helper (App Sandbox/XPC or an equivalent sandbox profile) with no
network entitlement, read access only to one staged input, write access only to a
staging directory, explicit memory/CPU limits, and a narrow serialized result
contract.

### 2. [P2] The renderer CSP permits connections to every loopback port

**Evidence.** The CSP at `desktop/src-tauri/tauri.conf.json:28` allows
`http://127.0.0.1:*` so PDF.js can make range requests to the random-port asset
endpoint. Asset access itself is protected by a random, hashed, asset-scoped capability
and an origin allowlist at `src/research_memory/api.py`; capabilities last up to twelve
hours so lazy PDF range requests survive a work session and are all revoked on private-core
restart. The core session token and raw paths never enter the renderer.

**Impact.** If renderer script execution were compromised, the renderer could send
requests to unrelated HTTP services listening on loopback. Same-origin response
reading is still constrained, but state-changing local endpoints are a concern.

**Recommendation.** Serve range-capable PDF bytes through a Tauri custom protocol or
a Rust proxy command, then remove the wildcard loopback source from `connect-src`.
Keep the capability and origin checks as defense in depth.

### 3. [P3] Backup passphrases cannot be guaranteed to be zeroized

**Evidence.** The passphrase is held in React state at
`desktop/src/App.tsx:668-705`, passed through a Rust `String` beginning at
`desktop/src-tauri/src/lib.rs:599`, and decoded into a Python request model.
The UI clears its state after every operation and no layer logs or persists the
passphrase, but managed-language and serialization buffers may remain until reused.

**Impact.** A same-account memory inspection or crash dump taken during backup or
restore could recover a passphrase.

**Recommendation.** Move passphrase entry and key derivation into a native dialog and
Rust crypto boundary using zeroizing buffers, pass only derived key material to a
dedicated backup helper, disable sensitive crash capture, and document that backup
passphrases should not be reused.

### 4. [P3] Development-only legacy web routes remain in the sidecar package

**Evidence.** Desktop mode forcibly disables legacy web access in
`src/research_memory/cli.py:40-53`, middleware returns 404 for non-API routes at
`src/research_memory/main.py:292-295`, and API documentation is disabled. However,
the Jinja/static route implementation remains compiled into the sidecar beginning at
`src/research_memory/main.py:310`.

**Impact.** Unreachable code still increases dependency and maintenance surface and
could become reachable through a future configuration regression.

**Recommendation.** Split the legacy prototype into a development-only package and
exclude it, Jinja, multipart form handlers, and static assets from the signed sidecar.

## Verified controls

- Rust generates a random loopback port and 256-bit session token, passes the token
  only to the sidecar environment, and proxies typed commands. The renderer has only
  Tauri core permissions.
- The core rejects non-loopback clients, uses constant-time token comparison, disables
  production API documentation, validates typed request bodies, and returns redacted
  job/support errors.
- Managed PDFs are SHA-256 addressed, atomically published, integrity-checked before
  use, and never overwritten. Trash cannot unlink source paths.
- Portable backups use Scrypt plus streaming AES-GCM. Restore validates the exact
  archive member set, sizes, hashes, schema version, and SQLite integrity before
  replacing the live database (`src/research_memory/services/backup.py:78` and
  `src/research_memory/services/backup.py:202`).
- Online metadata is opt-in, uses fixed Crossref/PubMed hosts, sends identifiers only,
  and disables redirects. Cloud AI is absent from the beta.
- Updates require HTTPS and signed updater metadata in release configuration; the
  macOS build uses hardened runtime, signing, notarization, and stapling.

## Verification performed

- `pip-audit`: no known vulnerabilities after upgrading `cryptography` to 48.0.1.
- `npm audit --omit=dev`: no known vulnerabilities.
- `cargo-audit 0.22.2`: no known vulnerabilities after upgrading transitive `plist`,
  `quick-xml`, and `time`; 17 unmaintained/unsoundness warnings remain in transitive
  dependencies and should be rechecked on every lock update.
- License policy: passes across Python, Node, Rust, the locked OCR environment, and the
  pinned offline model.
- SBOM: CycloneDX generation covers all five of those release inputs with package hashes for
  the OCR runtime and model.
- Whole-SBOM vulnerability scan: no matches at the reviewed lock state; CI fails on any
  High or Critical match and archives the scanner report.
