# ADR 0001: Canonical Catalog with Personalized Display Projections

- Status: Accepted
- Date: 2026-07-27

## Context

Research papers routinely cross specialties, disease families, methods, populations, and
clinical activities. Copying a disease into each specialty tree would create conflicting
identities, duplicate assignments, and brittle migrations. A user’s specialty and interests
should influence navigation without changing the factual concepts supported by an article.

The product also needs offline operation, exact provenance, a safe catalog upgrade path, and
future local/cloud parity without making a mutable public database the authority for global
medical concepts.

## Decision

Use a bundled, versioned, content-hashed canonical catalog as the global source of truth.
Represent semantic relationships with canonical edges. Represent specialty behavior in
versioned packs. Generate a personalized display tree from profile selections, pack
inheritance, weights, and navigation overrides.

One canonical node may appear in multiple display locations through distinct stable
`display_instance_id` values. Article assignments store only canonical node IDs plus a
name snapshot. Display-only relationships are not semantic equivalence.

Store profile choices, overrides, assignments, human decisions, and manual disease-state
values as non-rebuildable local data. Treat classifier candidates, generated evidence, and
navigation/facet caches as rebuildable. Retire removed catalog nodes rather than deleting
them.

Bundle the global catalog in both local and future cloud clients. Cloud profile and
assignment rows will be owner-scoped in a later phase; public clients will not mutate the
global catalog.

Keep automatic suggestions, auto-apply, and disease-state extraction behind separate
feature flags and acceptance gates. Define classifier and terminology adapter interfaces
before implementations. Do not bundle or download licensed terminology without a separate
licensing decision.

## Consequences

Benefits:

- stable concept identity across specialties and catalog versions;
- personalized navigation without corrupting neutral article truth;
- explicit provenance, validation, and reproducible releases;
- safe retirement that preserves accepted and rejected user decisions;
- a shared contract boundary for Python, Rust, TypeScript, and future cloud work.

Costs:

- the display tree needs distinct instance identity and override logic;
- pack curation and catalog releases require validation and review;
- cross-language generated contracts must remain current;
- a starter catalog cannot claim complete clinical coverage.

## Rejected alternatives

- Specialty-specific copies of diseases: rejected because they duplicate canonical truth.
- A mutable client-writable cloud catalog: rejected because it weakens release provenance
  and tenant safety.
- Runtime scraping of certification or terminology sites: rejected because it is
  non-reproducible and creates licensing/provenance risk.
- Profile-weighted factual extraction: rejected because user preference cannot create
  unsupported article concepts.
- Enabling auto-apply with the initial seed: rejected until physician-reviewed precision and
  evidence gates pass.
