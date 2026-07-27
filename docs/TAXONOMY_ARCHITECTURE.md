# Personalized Medical Taxonomy Architecture

## Status and phase boundary

Phase 0 and Phase 1 provide the taxonomy foundation only. The application now has a
versioned bundled catalog, strict validation, local SQLite persistence, profile and manual
assignment services, a deterministic personalized-tree builder, and read-only catalog/tree
APIs. There is no questionnaire UI, taxonomy browser, automatic article classification,
review queue, cloud persistence, or Supabase migration in this phase.

The bundled data is a **versioned broad specialty and disease-family starter catalog** with
deeper curated packs for pulmonary disease, critical care, and interventional pulmonology.
It is not a complete clinical ontology and is not a source of patient-specific
recommendations.

## Canonical catalog and personalized view

Canonical nodes represent one stable concept each. Canonical `is_a` and `part_of` edges
carry semantic relationships. Specialty packs select and arrange those concepts; they do not
create specialty-specific copies. A profile selects packs and supplies personal relevance
weights.

`PersonalizedTaxonomyBuilder` produces a display projection:

```text
versioned catalog + selected packs + preferences + navigation overrides
                                  |
                                  v
                 personalized display instances
```

A canonical concept may have several `display_instance_id` values when it belongs under
several display parents. Article assignments always refer to the canonical node ID, never a
display instance. Profile weights affect navigation order only and cannot change neutral
article truth.

The builder is pure and deterministic. It resolves inherited packs, unions canonical IDs,
retains multiple display paths, applies hierarchy depth, and applies hide/pin/move/alias
overrides last. Its revision key includes the catalog and serialized profile inputs.

## Runtime layers

- Bundled JSON resources and JSON Schemas are the catalog source of truth.
- Generated Python and TypeScript literal unions come from those schemas.
- The Python loader verifies file membership, a content hash, strict shapes, references,
  cycles, credential counts, state dimensions, and pack resolution before installation.
- Migration 008 adds local catalog, profile, navigation, assignment, evidence, and decision
  tables.
- Catalog installation is transactional and idempotent. Removed canonical nodes are retired
  rather than deleted.
- The local API currently exposes read-only catalog search, node lookup, pack listing, and a
  generated tree through the authenticated loopback boundary.
- Rust and TypeScript mirror each exposed response; no raw filesystem paths are returned.

## Rebuildability

Non-rebuildable taxonomy data:

- profile answers, selections, preferences, and navigation overrides;
- user-created concepts when that capability is added;
- manual, accepted, human-verified, and rejected assignments;
- assignment decision history and manual state corrections;
- node-name snapshots retained with assignments.

Rebuildable taxonomy data:

- unaccepted classifier suggestions and classifier-generated evidence;
- candidate scores and input fingerprints;
- personalized-navigation and facet caches.

Catalog upgrades may recompute derived views, but must not delete or silently rewrite
non-rebuildable decisions.

## Local and cloud parity

| Capability | Local Phase 1 | Cloud target |
|---|---|---|
| Global catalog | Bundled, hashed, read-only | Same bundled release; not client-writable |
| Profile and selections | SQLite service | Owner-scoped rows in Phase 5 |
| Navigation overrides | SQLite service | Owner-scoped rows in Phase 5 |
| Manual assignments and decisions | SQLite service contract | Owner/library-scoped rows in Phase 5 |
| Personalized tree | Python deterministic builder | Equivalent contract and golden fixtures |
| Automatic suggestions | Disabled and unimplemented | Deferred until Phase 4 validation |

Cloud parity is a design requirement, not a claim that taxonomy sync is implemented. Global
catalog content remains release-managed rather than mutable through a public cloud client.

## Feature gates

- `taxonomy_profile_enabled=true`: enables the local catalog/profile foundation and read-only
  taxonomy endpoints.
- `taxonomy_suggestions_enabled=false`: no automatic suggestions are produced or surfaced.
- `taxonomy_auto_apply_enabled=false`: no classifier output may become accepted organization
  automatically.
- `taxonomy_disease_state_extraction_enabled=false`: automatic state extraction remains
  unavailable.

The last three defaults must not be loosened merely because unit tests pass. Their validation
requirements are recorded in
[`TAXONOMY_ACCEPTANCE_GATES.md`](TAXONOMY_ACCEPTANCE_GATES.md).

## Trust and terminology boundaries

The catalog supports empty external mappings and defines an adapter boundary for future
terminology providers. It does not bundle or download SNOMED CT, UMLS, ICD, RxNorm, LOINC,
or other licensed vocabularies. External codes must never be invented; authoritative
mappings require provenance, version, verification status, and compatible licensing.

The current beta organizes published literature. It does not ingest PHI, perform bedside
decision support, infer patient-specific treatment, or replace a clinical terminology
system.
