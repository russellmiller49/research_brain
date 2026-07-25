# Product concept: an AI-native “research memory”

The finished product should not feel like a folder organizer with a chatbot attached. It should feel like a **personal research memory system** that turns thousands of PDFs into an organized, searchable, auditable body of knowledge.

Its central promise would be:

> **Find a paper using whatever fragment you remember, understand why it matters, compare it with related evidence, and return to the exact source in seconds.**

A working name could simply be **Research Memory** until the product develops a distinct identity.

---

## 1. What the finished product looks like

The primary application should be a **desktop-first library for macOS and Windows**, because the source material already lives on the user’s computer. It could have encrypted synchronization and a browser companion, but it should remain fully useful offline.

The interface would have six principal areas:

| Area               | Purpose                                                                              |
| ------------------ | ------------------------------------------------------------------------------------ |
| **Inbox**          | Newly imported or saved papers awaiting review                                       |
| **Library**        | Every article, searchable and filterable                                             |
| **Topics**         | Automatically organized concept pages                                                |
| **Projects**       | Focused literature reviews, manuscripts, guidelines, courses, and research questions |
| **Alerts**         | New papers, corrections, retractions, and important updates                          |
| **Ask My Library** | Source-grounded questions across selected or all documents                           |

The top of every screen would contain a universal search box:

> **What are you trying to remember?**

A user could type:

* “The paper where navigation success was high but diagnostic yield was much lower.”
* “A prospective bronchoscopy study from around 2021 with a low pneumothorax rate.”
* “The study that excluded lesions without a bronchus sign.”
* “A trial with about 200 patients where mortality was the secondary endpoint.”
* “The paper I saved during fellowship about false-negative EBUS.”
* “The meta-analysis with a forest plot showing substantial heterogeneity.”
* “The article where I highlighted the difference between technical success and clinical success.”

The system would search not only titles and abstracts, but also:

* Full text
* Tables and figure captions
* Extracted study characteristics
* References
* Highlights and annotations
* Personal notes
* The date and context in which the article was saved
* Related articles and citation relationships
* Numerical results, including approximate values

---

# 2. The home screen

The home screen would function as a research command center rather than a static library.

It might show:

### Search from memory

A large natural-language search field with recent queries and example prompts.

### Research inbox

New documents would appear here after being:

* Downloaded into a watched folder
* Saved through a browser extension
* Imported from Zotero, EndNote, Mendeley, Paperpile, or a reference file
* Added from email or a cloud-storage folder
* Sent from a mobile device

Each item would initially have a simple triage action:

* Read soon
* Keep for reference
* Add to project
* Archive
* Delete
* Duplicate
* Not relevant

### Recently active topics

Examples might include:

* Robotic bronchoscopy
* EBUS staging
* Pleural infection
* ECMO anticoagulation
* Mechanical circulatory support
* Diagnostic yield definitions

Each topic card would show:

* Number of owned papers
* Number of unread papers
* New papers since the user last reviewed the topic
* Unresolved contradictions
* Current projects using the topic
* Recently added notes

### Papers worth resurfacing

Instead of random reminders, the system would identify papers that are likely to be useful because they:

* Relate to an active project
* Have not been opened recently
* Are frequently cited by newly added papers
* Contain highlights relevant to a current query
* Were saved but never reviewed
* Have recently received a correction, commentary, or follow-up study

### Current projects

Each project would display progress, recent additions, pending review tasks, and new relevant evidence.

---

# 3. Importing and organizing the existing PDF library

The first major challenge is turning a disorganized folder of PDFs into a reliable collection without requiring the user to manually tag everything.

## Automatic library ingestion

The application would let the user select one or more folders to watch. It would then progressively process the files in the background.

It should:

* Recognize article PDFs even when filenames are unhelpful
* Extract DOI, PMID, title, authors, journal, and publication year
* Match metadata against authoritative bibliographic databases
* Identify exact duplicates
* Identify likely duplicate versions
* Connect preprints with final publications
* Group supplements with the primary article
* Recognize accepted manuscripts and publisher versions
* Preserve the original file
* Optionally offer standardized filenames without moving anything unexpectedly
* Track the original file location

Importantly, the product should use **virtual organization**. A paper could appear in multiple topics and projects without creating duplicate files.

## Handling imperfect PDFs

The system would need to recognize and appropriately process:

* Scanned PDFs
* Two-column layouts
* Articles with missing metadata
* Conference abstracts
* Supplements
* Book chapters
* Guidelines
* Articles containing primarily images
* Password-protected or corrupted documents
* Older papers without a DOI
* PDFs containing several articles in one file

It should clearly display processing status:

* Fully indexed
* Metadata incomplete
* OCR required
* Full text unavailable
* Tables partially extracted
* Manual review recommended

---

# 4. The article index

Every imported article would generate a structured **article card**. This card would be the foundation of the searchable index.

## Core bibliographic information

* Title
* Authors
* Journal
* Publication date
* DOI
* PMID or other identifiers
* Article type
* File location
* Version information
* Retraction, correction, or erratum status

## Structured research information

For medical literature, the system could extract:

| Field                     | Examples                                                                                           |
| ------------------------- | -------------------------------------------------------------------------------------------------- |
| **Research question**     | Primary question addressed by the study                                                            |
| **Study design**          | RCT, prospective cohort, retrospective cohort, diagnostic accuracy study, meta-analysis, guideline |
| **Setting**               | Single center, multicenter, community, academic, ICU                                               |
| **Population**            | Disease, severity, inclusion criteria, exclusion criteria                                          |
| **Sample size**           | Overall and by group                                                                               |
| **Intervention**          | Procedure, drug, device, strategy, diagnostic test                                                 |
| **Comparator**            | Standard care, alternate device, placebo, historical control                                       |
| **Primary outcome**       | As defined by the authors                                                                          |
| **Secondary outcomes**    | Additional prespecified outcomes                                                                   |
| **Follow-up**             | Duration and completeness                                                                          |
| **Key findings**          | Effect sizes, confidence intervals, event rates, test characteristics                              |
| **Limitations**           | Author-stated and user-added limitations                                                           |
| **Funding and conflicts** | As reported in the article                                                                         |
| **Definitions**           | How the paper defines yield, response, success, complication, or other central terms               |

The extraction should not be presented as unquestionable truth. Every field would include:

* A link to the supporting page
* Highlighted source text
* Extraction confidence
* An edit or correction control
* A marker distinguishing author-reported facts from AI interpretation

## Personal information layer

Each paper would also contain the user’s private intellectual context:

* Why I saved this
* My summary
* My critique
* Important quotations
* Clinical implications
* Research ideas
* Teaching points
* Manuscripts or projects using the paper
* Questions to revisit
* Reading status
* Importance rating
* Custom tags

This personal layer is one of the product’s strongest differentiators. Two researchers can own the same PDF but remember and use it for entirely different reasons.

---

# 5. The paper-reading screen

Opening an article would produce a three-part workspace.

## PDF viewer

The central pane would contain the original PDF with:

* Search
* Highlights
* Comments
* Bookmarks
* Figure navigation
* Table navigation
* Reference links
* Page thumbnails
* Citation copying
* Side-by-side article comparison

Annotations should remain exportable rather than being trapped in the application.

## Structured study card

A side panel would display the extracted article index:

* Study design
* Population
* Intervention and comparator
* Outcomes
* Key numerical findings
* Limitations
* Funding
* Related papers

Selecting any fact would jump to the exact supporting passage, table, or figure.

## Research assistant

The user could ask questions about the open article:

* “What was the primary endpoint?”
* “How was diagnostic yield defined?”
* “Was the analysis intention-to-treat?”
* “What were the exclusion criteria?”
* “Which complications were adjudicated?”
* “Summarize the limitations stated by the authors.”
* “Find every place the paper discusses bronchus sign.”
* “Does the abstract accurately represent the full results?”

Each answer would cite the relevant pages and expose the underlying passages. When the source does not answer the question, the system should say so rather than infer a response silently.

---

# 6. Search designed around human memory

This should be the product’s defining feature.

Traditional literature databases require the user to remember searchable bibliographic information. This system would accept the way people actually remember papers: approximately, incompletely, and through small details.

## Hybrid search

The search engine would combine:

* Exact keyword search
* Semantic similarity
* Metadata matching
* Acronym and synonym expansion
* Numerical matching
* Citation relationships
* Personal notes and highlights
* Reading and save history
* Topic classification
* Figure and table captions

For example, “the study with around a 10% complication rate” should not search only for the literal phrase “10%.” It should recognize nearby values, event-rate terminology, complications reported in tables, and the clinical topic implied by the rest of the query.

## Search result cards

Each result would explain **why it matched**:

> **Why this may be the paper:**
> The article reports an 11.2% overall adverse-event rate in Table 3. You highlighted the complications section in March 2024 and added the note “higher than expected despite technical success.”

The result card would include:

* Title and citation
* Study type
* One-sentence description
* Exact matching passages
* Matching table or figure
* Personal notes that contributed to the result
* Related topic
* Date saved and last opened
* Confidence that this is the remembered paper

## Search scopes

The user could search:

* Entire library
* One topic
* One project
* Selected papers
* Notes only
* Tables and figures only
* Unread papers
* Guidelines only
* Primary studies only
* A defined publication period

## Search refinement through conversation

After a broad query, the system could refine results conversationally:

> “Do you remember whether this was a diagnostic study or a therapeutic trial?”

However, it should show useful initial results immediately rather than requiring a series of questions before searching.

---

# 7. Topic pages: turning documents into knowledge

A topic page would be a living, editable synthesis of everything in the user’s library related to a concept.

For example, a topic page for **robotic bronchoscopy** could contain:

## Topic overview

A concise description generated from the user’s library, with every factual statement linked to supporting papers.

## Subtopics

* Platform characteristics
* Navigation confirmation
* Cone-beam CT
* Radial EBUS
* Bronchus sign
* Diagnostic yield definitions
* Safety outcomes
* Learning curve
* Cost and resource use

## Evidence timeline

A chronological view showing:

* Early feasibility reports
* Larger retrospective studies
* Prospective studies
* Comparative studies
* Meta-analyses
* Guidelines
* Follow-up analyses

## Key papers

Papers could be ranked differently depending on the user’s goal:

* Most foundational
* Highest-quality evidence
* Most cited
* Most recently published
* Most frequently used by the user
* Most relevant to an active project
* Contradictory or outlying findings

## Areas of agreement

Statements supported by several independent sources.

## Areas of disagreement

The application would display disagreements rather than averaging them away:

* Different outcome definitions
* Conflicting effect estimates
* Different patient populations
* Distinct device generations
* Variation in follow-up
* Duplicate or overlapping cohorts
* Different reference standards

## Knowledge gaps

Potential gaps might include:

* Outcomes not adequately measured
* Populations repeatedly excluded
* Lack of prospective comparison
* Inconsistent definitions
* Insufficient follow-up
* Limited external validation

These should be presented as evidence-map observations, not automatically asserted research conclusions.

## Personal synthesis

The user could write an editable “What I currently think” section. The system might help draft it, but it would remain explicitly separate from extracted source content.

---

# 8. Projects: where literature becomes work

A project would be a focused workspace built on top of the general library.

Possible project types could include:

* Manuscript
* Grant
* Guideline
* Systematic review
* Narrative review
* Lecture
* Fellowship curriculum
* Journal club
* Clinical protocol
* Research proposal
* Board-review module

## Project definition

At creation, the user could specify:

* Central question
* PICO or other framework
* Scope
* Inclusion and exclusion rules
* Important outcomes
* Deadline
* Collaborators
* Required deliverables

## Project paper board

Papers could move through configurable stages:

* Candidate
* To review
* Included
* Excluded
* Background only
* Awaiting full text
* Data extracted
* Ready for synthesis

Exclusion decisions could include reasons, particularly in systematic-review mode.

## Evidence matrix

The application would automatically create a table with one paper per row and structured fields such as:

* Study design
* Population
* Sample size
* Intervention
* Comparator
* Primary outcome
* Effect estimate
* Follow-up
* Limitations
* Risk-of-bias notes
* User comments

Every cell would remain linked to its source.

## Compare mode

The user could select several papers and request:

* Side-by-side design comparison
* Differences in inclusion criteria
* Differences in outcome definitions
* Numerical result comparison
* Identification of potentially overlapping cohorts
* Methodological differences that may explain discordant findings
* Comparison of abstract conclusions with reported results

## Outputs

Projects could export:

* Markdown
* CSV or Excel
* Word
* RIS
* BibTeX
* CSL JSON
* Evidence tables
* Annotated bibliographies
* Literature review outlines
* Source-grounded summaries
* Presentation-ready tables
* Machine-parseable knowledge extracts

For your own work, a particularly useful output would be a **dense knowledge-document mode** that converts selected papers into structured, citation-preserving extracts suitable for educational modules or downstream AI agents.

---

# 9. Capturing why an article was saved

This may be one of the most valuable and defensible features.

When saving an article through the browser extension, the application could offer a brief optional prompt:

> **Why are you saving this?**

The user could type or dictate:

* “Useful definition of procedural success.”
* “Potential citation for introduction.”
* “Complication rate seemed unexpectedly low.”
* “Need to compare this with our institutional data.”
* “Good figure for teaching fellows.”
* “Possible duplicate cohort.”
* “Review later for guideline project.”

The software would also capture context, with permission:

* Search query that led to the paper
* Web page from which it was saved
* Project active at the time
* Folder or collection selected
* Highlighted abstract text
* Date and device

Years later, the user could search those reasons directly.

For an existing collection, the application could infer probable topics and relationships, but it should not pretend to know why the user originally saved an article.

---

# 10. Asking questions across the library

The product would include a source-grounded research assistant, but the assistant would be integrated into the library rather than being the entire product.

## Query examples

* “How do the papers in this project define diagnostic yield?”
* “Which studies included only peripheral lesions?”
* “Find prospective studies with at least 12 months of follow-up.”
* “Which papers reported severe bleeding?”
* “What evidence in my library supports this paragraph?”
* “Which studies are likely reporting overlapping patient cohorts?”
* “Summarize the arguments for and against routine mediastinal staging in this population.”
* “Show me where these two reviews disagree.”
* “Create a table of sensitivity, specificity, and prevalence.”
* “Which claims in my draft are not supported by a paper in this collection?”

## Answer structure

A strong answer would distinguish:

1. **Directly reported findings**
2. **Cross-paper synthesis**
3. **Possible interpretation**
4. **Uncertainty or missing information**

Every claim would link to the exact paper and page. The user could expand a citation to see the supporting passage without leaving the answer.

The system should also allow:

* “Answer only from selected papers.”
* “Exclude narrative reviews.”
* “Use primary studies only.”
* “Do not infer beyond what the authors state.”
* “Show conflicting evidence.”
* “Include exact numbers and units.”
* “Return a machine-readable table.”

---

# 11. Figures, tables, and visual memory

Many people remember an article through a figure rather than its title. A mature version of the product should index visual content.

It could allow searches such as:

* “The Kaplan–Meier curve showing early separation.”
* “The forest plot with only a few studies and a very wide confidence interval.”
* “The airway diagram comparing three approaches.”
* “The table listing device generations.”
* “The study with the unusually complicated CONSORT diagram.”

For each figure or table, the index could contain:

* Caption
* Article and page
* Figure type
* Extracted labels
* Associated text
* Numerical data when reliably recoverable
* User annotations

Visual extraction is technically difficult, so confidence and source verification would be especially important.

---

# 12. Relationships and knowledge graph

The system would build a graph of relationships across documents.

Possible relationships include:

* Cites
* Is cited by
* Uses the same dataset
* Appears to contain an overlapping cohort
* Is a follow-up study
* Is a secondary analysis
* Is a protocol for
* Is corrected by
* Is commented on by
* Is included in a meta-analysis
* Supports a guideline recommendation
* Uses the same intervention
* Uses a different definition of the same outcome
* Contradicts
* Replicates
* Shares authors or institutions

The graph should be available as an exploration tool, but users should not be forced to navigate a visually complicated network. The more practical value would be embedded throughout the product:

> “This article appears to be a secondary analysis of a cohort already represented by two papers in this project.”

---

# 13. Proactive literature monitoring

Once the system understands a user’s topics and projects, it could monitor newly published literature.

The important distinction is that it should not merely send keyword alerts. It should compare new papers with the user’s existing knowledge.

An alert might say:

> **Potentially important update for your EBUS staging project**
> This prospective study evaluates a population excluded from most papers currently in your collection. It uses a different definition of false-negative staging and reports longer follow-up.

Other alerts could include:

* Follow-up to a paper in the library
* New guideline citing several owned papers
* Correction or retraction
* New study using a previously understudied population
* Result that conflicts with the dominant evidence in the library
* Publication of the final version of an owned preprint
* Newly released supplementary material
* Highly relevant paper missing from an active project

Users would need strong control over frequency and thresholds to avoid creating another noisy notification system.

---

# 14. Collaboration

A team version could support shared research spaces without exposing each member’s entire personal library.

Features could include:

* Shared project collections
* Paper assignment
* Shared annotations
* Private annotations
* Discussion threads attached to passages
* Evidence-table editing
* Version history
* Review and approval of extracted facts
* Roles and permissions
* Institution-level libraries
* Audit trails
* Export packages for collaborators who do not use the application

For a guideline or systematic-review team, collaborators could verify individual extractions and mark them:

* Unreviewed
* AI extracted
* Human verified
* Disputed
* Needs adjudication

---

# 15. Trust, accuracy, and privacy

Trust should be treated as a central product feature, not a disclaimer added later.

## Source provenance

Every AI-generated factual statement should have an inspectable source. The application should never hide the distinction between:

* Text quoted from an article
* Structured information extracted from an article
* A synthesis across several articles
* The system’s interpretation
* The user’s own note

## Uncertainty

Low-confidence extraction should be visibly marked. A blank field is preferable to an invented one.

## User corrections

Users should be able to correct extracted information. The system would retain:

* Original extraction
* Corrected value
* Source passage
* Who made the correction
* Date of correction

## Privacy model

A strong design would be local-first:

* PDFs remain on the user’s computer by default
* Local keyword and semantic index
* Encryption at rest
* Optional encrypted synchronization
* Explicit controls over which model providers receive text
* No training on user data
* Ability to use local models
* Ability to delete derived indexes completely
* Separate handling for personal and institutional libraries

The initial product should be designed for published literature and should discourage uploading patient-identifiable information. A future clinical workspace would require a substantially different privacy, security, and regulatory design.

## Copyright

The product should index literature the user is authorized to possess. Shared workspaces should default to sharing metadata, citations, notes, and extracted facts rather than redistributing copyrighted PDFs without permission.

---

# 16. Integrations

The product would be more successful as a layer over the existing research ecosystem than as an immediate replacement for every other tool.

Important integrations would include:

* Zotero
* EndNote
* Mendeley
* Paperpile
* PubMed
* Crossref
* OpenAlex
* ORCID
* Google Drive
* OneDrive
* Dropbox
* Institutional library resolvers
* Microsoft Word
* Google Docs
* Obsidian
* Notion
* Markdown repositories
* Researcher browser extensions

Citation formatting should be available, but the product should not make bibliography management its primary identity.

---

# 17. What makes this different

Most existing products emphasize one of four things:

1. Citation management
2. Public literature discovery
3. PDF annotation
4. Chatting with individual documents

Your concept combines those functions around a different core object: **the researcher’s accumulated memory**.

The strongest differentiators would be:

### Search based on partial recollection

The user does not need the title, author, DOI, or exact terminology.

### Personal context

The software knows why a paper was saved, where it was used, what was highlighted, and how it relates to the user’s work.

### Structured evidence

A paper is not only a file. It becomes a study record containing design, population, methods, outcomes, and limitations.

### Living topic pages

The library organizes itself into evolving bodies of knowledge rather than static folders.

### Auditable AI

Every answer and extraction remains traceable to the original page.

### Long-term accumulation

The system becomes more useful over years because it learns the user’s vocabulary, topics, projects, corrections, and preferred organizational structure.

That accumulated personal knowledge graph could become the product’s most meaningful competitive advantage.

---

# 18. A realistic final-product workflow

Imagine you are preparing a lecture on diagnostic bronchoscopy.

You search:

> “The study where navigation success looked excellent, but strict diagnostic yield was lower, and I think the authors discussed benign follow-up.”

The system returns several candidates. The top result explains that it matched because:

* The paper separately reports navigation success and diagnostic yield
* Benign diagnoses required longitudinal confirmation
* You highlighted the outcome-definition section
* You saved it into a bronchoscopy folder three years ago

You open the article. The PDF jumps to the relevant methods section. The side panel displays the paper’s definition of diagnostic yield, sample size, reference standard, follow-up, and complications.

You select the paper and three related studies and click **Compare**. The resulting table shows that each study used a different denominator and different criteria for benign diagnoses.

You then open the **Diagnostic Yield Definitions** topic page. It displays:

* Papers grouped by definition
* A timeline of changing definitions
* Exact source passages
* Areas of disagreement
* Your prior notes
* Two newly published studies not yet in your library

You add the table to a lecture project and export it to Markdown or PowerPoint-ready format. Every table entry retains its article and page reference.

That is the type of experience that would make the product much more than a citation manager.

---

# 19. What should be built first

The complete vision is substantial. The first version should focus on one indispensable job:

> **Help a researcher find a half-remembered paper in a large private library faster and more reliably than any existing workflow.**

## Initial MVP

The first release should include:

1. Watched-folder and Zotero import
2. Metadata recovery and deduplication
3. Full-text indexing
4. Hybrid natural-language search
5. Search-result explanations with exact passages
6. PDF viewer
7. Paper notes and “why I saved this”
8. Basic study cards
9. Collections and projects
10. Source-grounded questions across selected papers
11. Local-first storage
12. RIS, BibTeX, CSV, and Markdown export

It should not initially attempt to perfect:

* Fully automated systematic reviews
* Autonomous risk-of-bias judgments
* Complex institutional collaboration
* Every possible article type
* Automatic clinical recommendations
* Complete extraction of all tables and figures

## Second stage

After the search experience is dependable:

* Rich medical study extraction
* Topic pages
* Evidence matrices
* Cross-paper comparison
* Citation and study-family relationships
* Figure and table indexing
* Correction and retraction monitoring

## Third stage

Once the personal knowledge model is mature:

* New-literature monitoring
* Collaboration
* Team adjudication
* Institutional deployment
* Mobile capture
* Domain-specific modules
* Curriculum and guideline synthesis
* Draft support with citation verification

---

# 20. The best initial market

The concept could eventually serve many professions, but the first version should be narrower.

A strong initial audience would be:

> **Physicians, biomedical researchers, and academic trainees with several hundred to several thousand locally stored research PDFs.**

Medical literature offers a valuable initial specialization because papers often have recurring structures:

* Population
* Intervention
* Comparator
* Outcomes
* Diagnostic performance
* Adverse events
* Follow-up
* Evidence hierarchy

A domain-specific medical version could outperform a generic PDF assistant while still using an architecture that later expands to other research fields.

---

# 21. Concise product specification

### Product

A local-first, AI-native research memory that transforms personal literature files into a searchable and evolving knowledge base.

### Primary user

A researcher with hundreds or thousands of saved papers who remembers concepts and details more readily than titles or citations.

### Primary job

Retrieve a half-remembered article and explain why it is relevant.

### Secondary jobs

* Understand an individual paper
* Compare studies
* Organize evidence by topic
* Build literature-based projects
* Preserve personal notes and reasoning
* Monitor meaningful new publications
* Produce source-grounded outputs

### Central design rule

No factual answer without an inspectable path back to the source.

### Core differentiator

The system indexes not only what each paper says, but also **what the paper means to its owner**.

### Long-term vision

A researcher’s entire accumulated literature collection becomes a persistent, navigable, and trustworthy extension of his or her memory.

The logical next artifact is a formal product requirements document with user stories, screen-level wireframes, data objects, MVP acceptance criteria, and a technical architecture suitable for a coding agent or development team.
