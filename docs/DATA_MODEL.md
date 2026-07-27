# Data Model

## Sources of truth

| Concept | Source of truth | Rebuildable |
|---|---|---|
| Article metadata and personal context | `documents` | No |
| Immutable PDF versions | `document_files` + SHA-256 object store | No |
| Notes and highlights | `notes`, `annotations` | No |
| Collections | `projects`, `project_documents` | No |
| Import/review history | `jobs`, external-source tables, `review_decisions` | No |
| Page layout and passages | `document_pages`, `document_chunks` | Yes |
| Lexical index | `document_chunks_fts` | Yes |
| Semantic index | memory-mapped USearch files + `index_state` | Yes |
| Versioned taxonomy catalog | bundled JSON + `taxonomy_*` catalog tables | Release-managed |
| Research profile and navigation | `research_profile*`, `user_navigation_overrides` | No |
| Manual/accepted/rejected taxonomy truth | `article_taxonomy_assignments`, `taxonomy_decision_history` | No |
| Unaccepted classifier suggestions/evidence | taxonomy assignment/evidence rows | Yes |

## Article and asset separation

`documents` represents an intellectual work. `document_files` represents immutable bytes
such as a preprint, publisher version, supplement, or alternate copy. A file belongs to one
article, but an article can have many file versions. The primary flag selects the default
reader asset without erasing the others.

SHA-256 is the exact-file identity. DOI and PMID are high-confidence article identifiers.
Normalized title is review evidence only and never an automatic merge key.

Zotero item, collection, attachment, and annotation identities live in separate external
relationship tables. Attachment versions map to managed assets without overloading file
identity, so a one-way local-API re-import is idempotent and never reads or writes Zotero's
SQLite database.

## Stable external contracts

`SearchHit`

- rank; article and asset IDs;
- page and passage IDs;
- source-exact snippet and PDF-point bounding boxes;
- structured observed match reasons;
- compact bibliographic and personal-context fields.

`ImportJob`

- ID, type, redacted source label, stage, status;
- current/total progress and normalized progress;
- retryability and redacted error code;
- count plus separately fetched redacted per-file import issues;
- creation and update timestamps.

`Annotation`

- immutable asset ID and article ID;
- page and annotation type;
- PDF quad points, selected text, context hash;
- color/comment and timestamps.

`ArticleAsset`

- file hash and display filename;
- role/version/source;
- availability and primary status;
- size, with no raw object/source path.

`TrashArticle`

- article ID and title;
- deletion and scheduled purge timestamps;
- no source filename, source path, or managed-object path.

Pydantic and Rust mirror these contracts. API inputs reject unknown fields.

## Taxonomy identity and persistence

`taxonomy_nodes` stores one canonical concept per stable ID. `taxonomy_edges` stores semantic
and navigation relationships, while `specialty_packs` and memberships describe versioned
views selected by a profile. Several display instances may reference one canonical node;
article assignments never reference display-instance IDs.

`research_profile`, selections, preferences, and navigation overrides are user-authored and
non-rebuildable. Manual, accepted, human-verified, and rejected assignments; decision
history; node-name snapshots; and manual state corrections are also non-rebuildable.
Unaccepted classifier suggestions, classifier evidence, candidate scores, input
fingerprints, and view/facet caches may be rebuilt.

Catalog installation is idempotent. A later release updates stable IDs in place and marks
removed concepts retired. It never deletes a canonical node referenced by user data. See
[`TAXONOMY_ARCHITECTURE.md`](TAXONOMY_ARCHITECTURE.md) for the full boundary.

## Review states

`ready` is the only no-review state. Other states include password required, malformed,
oversized, missing source, OCR/partial processing, possible duplicate, metadata conflict,
and multi-article suspicion. User resolutions are appended to `review_decisions` before
clearing a review state.

## Migration policy

`schema_migrations` records each numbered migration exactly once. Migrations are
transactional and preceded by a SQLite snapshot. Derived data carries an index/model
version. When extraction or model behavior changes, derived rows are discarded and rebuilt;
user-authored or bibliographic records are migrated in place.

Migration 008 adds taxonomy catalog, profile, navigation, assignment, evidence, and decision
tables without changing migrations 1–7. Catalog JSON remains the release source of truth;
SQLite is the installed local representation.
