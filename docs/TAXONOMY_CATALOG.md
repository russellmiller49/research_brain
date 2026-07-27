# Taxonomy Catalog

## Release identity

The bundled `taxonomy-v1` catalog is stored under
`src/research_memory/resources/taxonomy/v1/`. Its manifest records:

- semantic version `1.0.0`;
- source date `2026-07-27`;
- SHA-256 content hash
  `3cd164d585654d1d74267f70e441a558b75b8f000ca4b56616df6da86a0ce8e0`;
- every versioned JSON resource included in that hash.

Current validated totals are 741 canonical nodes, 376 edges, 22 synonyms, 154 packs, and 13
disease-state archetypes. The credential subset contains 24 certifying boards, 38 specialty
areas, and 89 canonical subspecialty areas. Every specialty and subspecialty selection has a
pack.

This is a **versioned broad specialty and disease-family starter catalog**. Broad packs have
`curation_status=starter`; they do not claim clinical completeness. Pulmonary disease,
critical care, and interventional pulmonology have deeper curated content.

## Resource layout

```text
catalog.json
credential_catalog.json
clinical_nodes.json
synonyms.json
edges.json
state_archetypes/*.json
packs/specialties/catalog.json
packs/subspecialties/catalog.json
packs/overlays/catalog.json
packs/focused_practice/catalog.json
packs/research_methods/catalog.json
```

Schemas live separately under `resources/taxonomy/schemas/v1/`. The schemas are also the
source for generated Python and TypeScript enum contracts. Run:

```bash
.venv-beta/bin/python scripts/validate_taxonomy_catalog.py
.venv-beta/bin/python scripts/generate_taxonomy_types.py --check
```

## Integrity rules

Catalog loading fails closed on:

- malformed JSON, duplicate object keys, schema violations, or unlisted files;
- a missing or incorrect manifest content hash;
- duplicate node, edge, pack, state-archetype, or normalized per-node synonym identities;
- unknown edge, synonym, pack, state-dimension, or display-parent references;
- canonical semantic cycles or pack-inheritance cycles;
- a pack member that is retired or a display path that cannot resolve;
- source metadata/count drift or a specialty/subspecialty without a pack.

IDs are stable, lowercase namespace identifiers such as `disease.copd`. Display location is
not encoded into canonical identity. `display_under` is navigation-only and is never treated
as semantic equivalence.

## Credential source verification

The seed was checked against the official ABMS
[Specialty and Subspecialty Certificates](https://www.abms.org/member-boards/specialty-subspecialty-certificates/)
page on 2026-07-27. The page continued to report 24 member boards, 38 specialty areas, and
89 subspecialty areas.

The following source-display differences are represented explicitly:

- ABMS displays Medical Physics as a grouped label. Diagnostic, Nuclear, and Therapeutic
  Medical Physics remain separate canonical specialty-area nodes so the official specialty
  count remains 38; metadata allows a UI to group them.
- `Anesthesiology Critical Care Medicine` and
  `Internal Medicine-Critical Care Medicine` resolve to the canonical subspecialty area
  `Critical Care Medicine`. Both Emergency Medicine offering labels are retained in edge
  metadata.
- `Pathology – Molecular Genetic` resolves to the canonical
  `Molecular Genetic Pathology` subspecialty area while retaining its board-specific source
  label.
- The source’s current `Maternal–Fetal Medicine` punctuation is preserved.
- Asterisk-marked offerings retain `approved_not_yet_issued` on the individual offering
  edge. A shared node stays active if another board already issues it.

No runtime scraper is used. A source change requires a reviewed catalog release, updated
source date/changelog, and a new immutable catalog version rather than silently changing an
installed version.

## Installation and upgrades

The installer validates before opening a transaction. A matching installed version and hash
is safe to install repeatedly. The same version with different source metadata is rejected.
On a new catalog release:

- matching canonical IDs are updated in place;
- missing prior nodes are marked `retired`;
- article assignments keep their canonical ID and `node_name_snapshot`;
- old packs become inactive and new pack manifests become active;
- no canonical node referenced by user data is deleted.

Migration 008 is additive. The migration runner snapshots the database before applying it
and rolls back the numbered migration transaction on failure.

## External terminology and licensing

External mappings are optional and empty in this seed. The adapter boundary permits a later
provider, but authoritative mappings must include vocabulary, code, version, provenance, and
verification. CI must not download licensed terminology. This catalog is not a substitute
for SNOMED CT, MeSH, UMLS, ICD, or another controlled clinical vocabulary.
