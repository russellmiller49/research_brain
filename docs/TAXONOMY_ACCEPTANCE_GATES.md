# Taxonomy Acceptance Gates

These gates supplement the beta-wide
[`ACCEPTANCE_GATES.md`](ACCEPTANCE_GATES.md). Passing Phase 1 tests authorizes the foundation
only; it does not authorize questionnaire UI, automatic classification, cloud persistence,
auto-apply, or automatic disease-state extraction.

## Catalog integrity

- 100% of catalog files validate against their versioned schemas.
- Every release has a version, source date, complete file list, and verified content hash.
- There are zero missing references and zero canonical or inheritance cycles.
- All official credential source entries are represented or explicitly documented.
- Shared subspecialty areas are canonicalized instead of duplicated.
- Every specialty and subspecialty pack resolves.
- Every state-archetype dimension resolves to a supported state node.
- Catalog installation is idempotent and a removed node is retired without orphaning an
  assignment.

Phase 1 automated checks enforce these conditions.

## Profile and navigation

- Draft profile state saves transactionally and resumes after restart.
- Completion is explicit; skip/resume UI behavior remains a Phase 2 gate.
- Specialty changes regenerate navigation without altering article assignments.
- A canonical disease can have multiple stable display instances.
- Multiple display placements never create duplicate canonical assignments.
- Inheritance, weighting, hierarchy depth, hide, pin, move, and alias behavior are
  deterministic.
- Profile choices affect display relevance only, never neutral article extraction.

## Classification trust

Before `taxonomy_auto_apply_enabled` may become true:

- at least 500 physician-reviewed articles across at least eight major specialty domains;
- at least 1,500 reviewed article-concept-role decisions;
- primary-disease and target-condition precision at least 95%;
- study-population precision at least 93%;
- complication precision at least 95%;
- zero visible reference-list-only assignments in the validation corpus;
- every visible automatic assignment resolves to stored evidence;
- rejected assignments are never silently restored;
- blank or uncertain output is preferred to an unsupported assignment.

Automatic classification is not implemented in Phase 1. Until these gates pass, even
high-confidence output remains suggested. Every disease-state field requires separate
field-specific validation and evidence before automatic extraction can be enabled.

## Performance

On the named 10,000-PDF baseline corpus:

- personalized-tree generation p95 is below 300 ms after catalog load;
- taxonomy facet query p95 is below 500 ms;
- the article taxonomy panel p95 is below 500 ms excluding PDF rendering;
- background classification does not make the UI unresponsive;
- backfill resumes without duplicate assignments;
- existing retrieval latency and quality do not materially regress.

Phase 1 unit tests do not substitute for the required corpus benchmark.

## Privacy and security

- No PDF text or profile content leaves the device in local mode.
- The future questionnaire requests no PHI.
- Support bundles and diagnostics remain content-free and exclude profile and article
  classification details.
- No service-role secret is present in client code.
- Future cloud rows are owner/library scoped and pass two-user RLS isolation tests for every
  operation.
- Global catalog data is bundled and cannot be mutated by a public cloud client.

## Accessibility and durability

- Phase 2 wizard and Phase 4 review queue must be keyboard-operable, have accessible names,
  avoid color-only confidence communication, and have no serious/critical axe violations.
- Migration 008 is transactional and snapshot-protected.
- Backup/restore must preserve profile data, navigation overrides, manual/accepted/rejected
  assignments, decision history, and manual state values before the feature ships.
- Catalog upgrades cannot orphan accepted assignments.
- Future classifier jobs resume exactly once after a crash.

## Current flag decision

| Flag | Default | Gate state |
|---|---:|---|
| `taxonomy_profile_enabled` | `true` | Phase 1 foundation covered by tests |
| `taxonomy_suggestions_enabled` | `false` | Phase 4 not started |
| `taxonomy_auto_apply_enabled` | `false` | Benchmark not run |
| `taxonomy_disease_state_extraction_enabled` | `false` | Field validation not run |
