# Research Memory macOS Beta Product Requirements

## Product promise

Research Memory helps a biomedical researcher recover a half-remembered paper and return to
the exact supporting passage without uploading their library. It treats personal context as
first-class information and an article as distinct from any one PDF version.

## Release audience and platform

- Closed beta: 20–50 biomedical users.
- Apple-silicon Macs running macOS 13 or newer.
- Notarized direct-download DMG with a signed in-app update channel.
- Libraries up to 10,000 PDFs and approximately 250,000 pages.
- Legally obtained published literature only; no PHI or clinical records.

## Required user journeys

### Onboard

The user can choose a folder through a native picker, understand that Research Memory makes
immutable managed copies, optionally connect Zotero, install the offline semantic model, and
configure an encrypted backup destination. Network metadata remains off until explicit
consent.

### Import and review

The user can import files or folders without blocking the interface and inspect durable job
progress. Interrupted work resumes from checkpoints. Exact hashes and matching DOI/PMID may
merge automatically. Title-only duplicates, metadata conflicts, encrypted documents,
malformed documents, multi-article PDFs, and missing files require an explicit review.

Deleting an article sends the app record and managed object to 30-day recoverable trash. It
never deletes or edits the source file.

### Recall search

The user can search using remembered wording, meaning, metadata, numbers, or personal notes;
filter by year, type, status, and project; see why every hit matched; and open the cited page
and source coordinates. The product never displays a fabricated percentage-style relevance
score.

### Read and annotate

The reader provides virtualized pages, thumbnails, outline, page and zoom controls,
in-document find, keyboard shortcuts, resizable panes, passage highlights, bookmarks,
highlights, comments, and editable personal context. The original PDF remains immutable.

### Organize and export

The user can create projects/collections, add papers, and export Markdown, RIS, BibTeX,
XFDF, or a new annotated PDF. Backup exports are passphrase-encrypted and restore verifies
database and object integrity.

### Personalized taxonomy foundation

Phase 1 provides a versioned broad specialty and disease-family starter catalog, local
profile persistence, and a deterministic personalized navigation projection. Canonical
concept identity remains separate from display placement, and profile relevance must never
change neutral article truth.

The questionnaire, taxonomy browser, manual reader organization, automatic suggestions,
review queue, and cloud synchronization are later-phase requirements and are not exposed by
the current implementation. The catalog is not clinically complete and the product does not
make patient-specific recommendations.

## Data and provenance rules

Every search hit identifies its article, asset version, page, passage, snippet, bounding
boxes, rank, and observed match signals. Every annotation records the asset version, page,
quad points, selected text, context hash, color/comment, and timestamps.

Displayed snippets must exist on the cited page. Source highlights must resolve to stored
coordinates. A file hash identifies immutable bytes; filenames, source paths, import sources,
roles, and versions are independent metadata.

## Offline and privacy behavior

Core workflows work offline. Crossref/PubMed enrichment is optional and sends only DOI/PMID.
Zotero access is local and read-only. Cloud AI is not part of the beta. Diagnostics are
opt-in and exclude user content and identifiers that could reveal library contents.

## Explicitly deferred

- Q&A and cloud AI
- Structured study cards and systematic-review extraction
- Topic synthesis and evidence timelines
- Alerts and literature monitoring
- Sync and collaboration
- Windows, mobile, and browser capture
- Table and figure understanding
- Autonomous clinical or research recommendations
- Automated taxonomy classification or disease-state extraction before its acceptance gates
  pass

The dormant v0.1 browser prototype is retained only to support migration/debugging and is
disabled in the desktop sidecar.

## Release gates

The beta must satisfy the measurable retrieval, ingestion, performance, provenance, export,
recovery, and reliability criteria in
[`ACCEPTANCE_GATES.md`](ACCEPTANCE_GATES.md). Shipping code and CI are necessary but not
sufficient: the 300-query expert benchmark, 10,000-PDF scale run, compatibility corpus,
recovery drills, design-partner trial, and two-week no-data-loss observation must be
completed with recorded evidence.
