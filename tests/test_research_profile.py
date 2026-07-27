from __future__ import annotations

import pytest

from research_memory.contracts import (
    NavigationOverride,
    ProfileSelection,
    ResearchProfileUpdate,
)
from research_memory.db import Database
from research_memory.services.personalized_taxonomy import PersonalizedTaxonomyBuilder
from research_memory.services.research_profile import (
    ResearchProfileError,
    ResearchProfileService,
)
from research_memory.services.taxonomy_catalog import TaxonomyCatalog


@pytest.fixture
def profile_services(tmp_path):
    db = Database(tmp_path / "profile.sqlite3", tmp_path / "backups")
    db.initialize()
    catalog = TaxonomyCatalog.load()
    catalog.install(db)
    return (
        db,
        catalog,
        ResearchProfileService(db, catalog),
        PersonalizedTaxonomyBuilder(catalog),
    )


def _update(**changes):
    values = {
        "catalog_version": "taxonomy-v1",
        "role_type": "physician_researcher",
        "questionnaire_version": "profile-v1",
        "raw_answers": {"step": 2},
        "preferences": {"prompt_why_saved": True},
        "selections": [
            ProfileSelection(
                node_id="specialty.internal_medicine",
                relationship_type="primary_specialty",
                priority_weight=0.7,
            ),
            ProfileSelection(
                node_id="subspecialty.pulmonary_disease",
                relationship_type="subspecialty",
                priority_weight=1,
            ),
        ],
    }
    values.update(changes)
    return ResearchProfileUpdate(**values)


def _walk(roots):
    for root in roots:
        yield root
        yield from _walk(root.children)


def test_profile_draft_save_resume_completion_and_idempotence(profile_services):
    _, _, service, _ = profile_services
    first = service.save(_update())
    second = service.save(_update())
    assert first.raw_answers == second.raw_answers == {"step": 2}
    assert len(second.selections) == 2
    assert second.preferences["prompt_why_saved"] is True
    assert second.onboarding_completed is False
    assert service.complete().onboarding_completed is True
    assert service.get().onboarding_completed is True


def test_profile_rejects_wrong_catalog_and_multiple_primary_specialties(profile_services):
    _, _, service, _ = profile_services
    with pytest.raises(ResearchProfileError, match="catalog version"):
        service.save(_update(catalog_version="taxonomy-v2"))
    with pytest.raises(ResearchProfileError, match="Only one primary"):
        service.save(
            _update(
                selections=[
                    ProfileSelection(
                        node_id="specialty.internal_medicine",
                        relationship_type="primary_specialty",
                    ),
                    ProfileSelection(
                        node_id="specialty.pediatrics",
                        relationship_type="primary_specialty",
                    ),
                ]
            )
        )
    with pytest.raises(ResearchProfileError, match="does not accept disease"):
        service.save(
            _update(
                selections=[
                    ProfileSelection(
                        node_id="disease.copd",
                        relationship_type="primary_specialty",
                    )
                ]
            )
        )


def test_personalized_tree_inheritance_weights_and_multiple_display_instances(
    profile_services,
):
    _, _, service, builder = profile_services
    profile = service.save(_update())
    tree = builder.build(profile)
    assert [root.canonical_node_id for root in tree.roots[:2]] == [
        "subspecialty.pulmonary_disease",
        "specialty.internal_medicine",
    ]
    instances = list(_walk(tree.roots))
    pulmonary_hypertension = [
        item for item in instances if item.canonical_node_id == "disease.pulmonary_hypertension"
    ]
    assert len(pulmonary_hypertension) >= 2
    assert len({item.display_instance_id for item in pulmonary_hypertension}) == len(
        pulmonary_hypertension
    )
    assert tree.total_canonical_nodes < len(instances)
    assert any(item.canonical_node_id == "disease.copd" for item in instances)


def test_navigation_overrides_apply_last(profile_services):
    _, _, service, builder = profile_services
    profile = service.save(
        _update(
            selections=[
                ProfileSelection(
                    node_id="subspecialty.pulmonary_disease",
                    relationship_type="subspecialty",
                    priority_weight=1,
                )
            ],
            navigation_overrides=[
                NavigationOverride(node_id="disease.asthma", action="hide"),
                NavigationOverride(
                    node_id="disease.copd",
                    action="alias",
                    display_alias="COPD papers",
                ),
                NavigationOverride(
                    node_id="disease.copd",
                    action="pin",
                    sort_order=-10,
                ),
                NavigationOverride(
                    node_id="disease.copd",
                    action="move",
                    display_parent_node_id="disease_family.pulmonary_vascular_disease",
                ),
            ],
        )
    )
    tree = builder.build(profile)
    instances = list(_walk(tree.roots))
    assert all(not item.visible for item in instances if item.canonical_node_id == "disease.asthma")
    copd = [item for item in instances if item.canonical_node_id == "disease.copd"]
    assert copd
    assert all(item.display_name == "COPD papers" for item in copd)
    assert all(item.pinned for item in copd)
    moved = copd[0]
    parents = {item.display_instance_id: item.canonical_node_id for item in instances}
    assert parents[moved.parent_display_instance_id] == (
        "disease_family.pulmonary_vascular_disease"
    )
