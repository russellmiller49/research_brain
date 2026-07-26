# Privacy Model

Research Memory is local-first. PDF import, text extraction, OCR, indexing, retrieval,
reading, annotation, and export do not require a network connection.

## Data that stays local

- PDF bytes and extracted text
- filenames and source paths
- search queries and result history
- notes, highlights, comments, summaries, and “why saved”
- projects and review decisions
- model embeddings and indexes
- backup passphrases and PDF passwords

PDF passwords are held only in process memory for the current session. Backup passphrases
are used for one operation and are not persisted.

## Optional network activity

Crossref/PubMed metadata enrichment is off by default. If enabled in Settings, only DOI or
PMID identifiers are sent; PDF text is never submitted. Zotero synchronization talks only to
Zotero’s loopback local API. Cloud AI is disabled and has no beta user interface.

Update checks use the configured HTTPS signed-update endpoint. The application installs only
an update whose Tauri signature verifies.

## Diagnostics

Diagnostics are opt-in. A support bundle contains version/schema information, aggregate
counts, redacted job errors, and recent application events. It excludes PDF text, snippets,
filenames, paths, identifiers, search queries, notes, annotations, and secrets. The current
beta does not automatically transmit a support bundle.

## At-rest protection

The beta relies on the macOS account boundary and recommends FileVault. Portable backups are
encrypted with AES-256-GCM using a Scrypt-derived key. The live library is not an
application-specific encrypted vault.

## Intended use

Use Research Memory for legally obtained published research. Do not store PHI, clinical
records, institutional secrets requiring a dedicated managed vault, or documents whose
licenses prohibit copying. The application does not make autonomous clinical
recommendations and is not a validated systematic-review adjudication system.
