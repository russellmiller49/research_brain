# Research Memory Product Requirements

## 1. Product statement

Research Memory is a local-first, AI-native literature workspace that makes a researcher’s accumulated PDF library retrievable by partial recollection, organizes it into evolving bodies of knowledge, and preserves an inspectable path from every extracted or synthesized claim to the original paper and page.

## 2. Primary user

The initial user is a physician, biomedical researcher, academic trainee, or evidence-synthesis professional with hundreds to thousands of personally saved PDFs distributed across local folders and citation-manager libraries.

## 3. Primary job to be done

> When I remember only an approximate feature of a paper, help me identify it quickly and explain why each result might be the paper I remember.

Examples include a sample size, an unexpected complication rate, an unusual exclusion criterion, a figure, a distinction between outcomes, or a personal note recorded years earlier.

## 4. Design principles

1. **Local-first by default.** Core ingestion and retrieval must work without an external service.
2. **Provenance before fluency.** Extracted and generated claims must retain source document and page.
3. **Personal context is first-class data.** Why a user saved a paper is as important as its bibliographic metadata.
4. **Articles are not files.** Multiple versions can belong to the same intellectual work.
5. **Uncertainty must be visible.** Absence is preferable to fabricated structured data.
6. **Organization should emerge without becoming opaque.** Automatic topics remain editable and inspectable.
7. **Interoperability over lock-in.** Bibliographic data, notes, evidence tables, and annotations must be exportable.

## 5. Implemented v0.1 scope

### Ingestion

- Upload PDFs into a managed library.
- Index local folders in place.
- Recursively scan subfolders.
- Register folders for later rescanning.
- Detect exact duplicate bytes.
- Attach likely alternate versions by DOI or normalized title.
- Extract text by page.
- Detect insufficient extractable text and flag OCR need.

### Article index

- Title, authors, journal, year, DOI, PMID, abstract, page count, and article type.
- Reading status and importance.
- Why saved, user summary, and page-linked notes.
- Basic machine-extracted study clues with confidence and page provenance.
- Automatically generated keyword signals.

### Retrieval

- Full-text search.
- Local passage-similarity search.
- Metadata and personal-context search.
- Filters by year, article type, reading status, and project.
- Ranked explanations of match signals.
- Result-to-page navigation.

### Evidence workspaces

- Project type, description, and central question.
- Candidate, review, included, excluded, background, extracted, and synthesis-ready statuses.
- Exclusion reasons.
- Evidence CSV, Markdown, RIS, and BibTeX export.

### Source-grounded Q&A

- Library-wide or project-scoped retrieval.
- Primary-study-only option.
- Extractive answer mode without an API.
- Optional OpenAI-compatible synthesis.
- Source passage cards with paper and page.

## 6. v0.2 requirements

### Ingestion reliability

- OCR queue with page-level confidence.
- Password entry for encrypted PDFs without persisting passwords.
- Background job table and resumable ingestion.
- Failed-file quarantine with actionable error messages.
- In-place reindexing after embedding-model changes.
- Automated watched-folder daemon with pause and resource limits.

### Interoperability

- Zotero database and storage import.
- RIS, BibTeX, and CSL JSON import.
- Browser extension capturing URL, search query, highlighted abstract text, and “why saved.”
- Obsidian-compatible Markdown note export.
- Citation-key collision resolution.

### Biomedical study extraction

Each field must store value, verbatim evidence span, page, extraction method, confidence, verification state, editor, and edit history.

Minimum fields:

- Research question
- Study design
- Setting
- Population and eligibility
- Sample size and analysis population
- Intervention or index test
- Comparator or reference standard
- Primary and secondary outcomes
- Follow-up
- Effect estimates with units and confidence intervals
- Complications
- Funding and conflicts
- Author-stated limitations
- Outcome definitions

### Verification workflow

- Unreviewed, AI extracted, human verified, disputed, and adjudicated states.
- Side-by-side source text and editable structured value.
- Bulk verification queue.
- Extraction accuracy audit export.

## 7. v0.3 requirements

- Figure and table detection, thumbnails, captions, and visual search.
- Reference parsing and citation graph.
- Preprint-to-publication linkage.
- Protocol, primary report, secondary analysis, and follow-up relationships.
- Possible overlapping-cohort detection using authors, sites, dates, sample size, and eligibility.
- Retraction, correction, expression-of-concern, and erratum monitoring.
- Draft claim-to-source verification.

## 8. Mature topic-page requirements

A topic page must contain:

- Editable scope definition
- Subtopics
- Evidence timeline
- Foundational and highest-quality papers
- Outcome-definition map
- Areas of independent convergence
- Areas of disagreement with candidate explanations
- Repeated exclusions and understudied populations
- Personal synthesis separated from source synthesis
- New-literature comparison against the owned corpus

The system must not silently average incompatible definitions or combine overlapping cohorts.

## 9. Desktop and collaboration requirements

### Desktop

- Tauri shell around the local web application.
- Native folder picker, file watching, system tray, and protocol links.
- Signed macOS and Windows installers.
- Encrypted operating-system credential storage.
- Automatic local backup and restore.

### Collaboration

- Share project metadata and annotations without requiring PDF redistribution.
- Private and shared notes.
- Role-based permissions.
- Extraction assignment, verification, dispute, and adjudication.
- Complete audit history.
- Institution-controlled model endpoints and storage policies.

## 10. Validation strategy

The product must be evaluated on real reference tasks rather than subjective demonstrations.

### Retrieval benchmark

- Build libraries of at least 1,000 papers.
- Capture natural half-memory queries from domain experts.
- Measure top-1, top-5, and top-10 retrieval.
- Compare keyword search, citation-manager search, dense retrieval, and hybrid retrieval.
- Stratify by query type: numerical memory, methods detail, visual memory, author/year, and personal context.

### Extraction benchmark

- Use completed high-quality reviews and guideline evidence tables as reference datasets.
- Separate extraction from adjudication and do not assume the published review is error-free.
- Measure exactness of population, design, outcomes, numerators, denominators, effect estimates, units, and source-page provenance.
- Track omission, unsupported extraction, and source-link errors separately.

### Human factors

- Time to recover a half-remembered article.
- Time to construct a project evidence table.
- Correction burden per article.
- Trust calibration: whether users appropriately verify low-confidence fields.
- Longitudinal value of “why saved” capture.

## 11. Non-goals for early releases

- Autonomous clinical recommendations
- Replacement of formal systematic-review adjudication
- Automated GRADE judgments presented as final
- Storage of protected health information
- Redistribution of copyrighted PDFs without authorization
- A generic chatbot without a structured library model
