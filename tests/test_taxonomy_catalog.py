from __future__ import annotations

import subprocess
import sys
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.main import create_app
from research_memory.services.taxonomy_catalog import (
    TaxonomyCatalog,
    TaxonomyCatalogValidationError,
    TaxonomyEdgeRecord,
)


def test_catalog_validates_source_counts_relationships_and_pack_integrity():
    catalog = TaxonomyCatalog.load()
    counts = Counter(node.node_type for node in catalog.nodes)
    assert catalog.manifest.catalog_version == "taxonomy-v1"
    assert catalog.credential_source.source_name == "American Board of Medical Specialties"
    assert catalog.credential_source.retrieved_date == "2026-07-27"
    assert counts["certifying_board"] == 24
    assert counts["specialty"] == 38
    assert counts["subspecialty"] == 89
    assert len(catalog.nodes) == len(catalog.nodes_by_id) == 741
    assert len(catalog.packs) == len(catalog.packs_by_id) == 154
    assert len(catalog.state_archetypes) == 13

    critical_care = [
        node
        for node in catalog.nodes
        if node.node_type == "subspecialty" and node.canonical_name == "Critical Care Medicine"
    ]
    assert len(critical_care) == 1
    offerings = [
        edge
        for edge in catalog.edges
        if edge.edge_type == "offered_by" and edge.child_id == critical_care[0].id
    ]
    source_names = {
        source_name
        for edge in offerings
        for source_name in edge.metadata.get(
            "source_offering_names",
            [edge.metadata["source_offering_name"]],
        )
    }
    assert {
        "Critical Care Medicine",
        "Anesthesiology Critical Care Medicine",
        "Internal Medicine-Critical Care Medicine",
    } <= source_names

    medical_physics = [
        node
        for node in catalog.nodes
        if node.node_type == "specialty" and node.metadata.get("display_group") == "Medical Physics"
    ]
    assert len(medical_physics) == 3
    pending_offerings = [
        edge
        for edge in catalog.edges
        if edge.metadata.get("offering_status") == "approved_not_yet_issued"
    ]
    assert len(pending_offerings) == 4
    assert all(pack.curation_status in {"starter", "curated"} for pack in catalog.packs)
    deep_pack_ids = {
        "pack.specialty.internal_medicine",
        "pack.subspecialty.pulmonary_disease",
        "pack.subspecialty.critical_care_medicine",
        "pack.focused_practice.interventional_pulmonology",
        "pack.overlay.diagnostic_accuracy",
        "pack.research_methods.systematic_review_and_meta_analysis",
        "pack.research_methods.guideline_development",
        "pack.research_methods.medical_education",
        "pack.research_methods.ai_in_medicine",
    }
    assert {
        pack_id
        for pack_id in deep_pack_ids
        if catalog.packs_by_id[pack_id].curation_status == "curated"
    } == deep_pack_ids
    assert all(
        dimension.id in catalog.nodes_by_id
        for archetype in catalog.state_archetypes
        for dimension in archetype.dimensions
    )
    interventional = catalog.packs_by_id["pack.focused_practice.interventional_pulmonology"]
    assert "pack.overlay.diagnostic_accuracy" in interventional.inherits
    pulmonary = catalog.packs_by_id["pack.subspecialty.pulmonary_disease"]
    canonical_children: dict[str, set[str]] = {}
    for edge in catalog.edges:
        if edge.edge_type in {"is_a", "part_of", "display_under"}:
            canonical_children.setdefault(edge.parent_id, set()).add(edge.child_id)

    pulmonary_concepts = {membership.node_id for membership in pulmonary.memberships}
    frontier = list(pulmonary_concepts)
    while frontier:
        for child_id in canonical_children.get(frontier.pop(), set()):
            if child_id not in pulmonary_concepts:
                pulmonary_concepts.add(child_id)
                frontier.append(child_id)
    assert {
        "disease.asthma",
        "disease.copd",
        "disease.cteph",
        "disease.idiopathic_pulmonary_fibrosis",
        "activity.screening",
        "activity.staging",
        "disease_family.cancer_treatment_complications",
    } <= pulmonary_concepts
    assert len(catalog.packs_by_id["pack.research_methods.medical_education"].memberships) >= 8
    assert len(catalog.packs_by_id["pack.research_methods.ai_in_medicine"].memberships) >= 8
    pediatric_pulmonology = catalog.packs_by_id["pack.subspecialty.pediatric_pulmonology"]
    assert {
        "pack.specialty.pediatrics",
        "pack.subspecialty.pulmonary_disease",
    } <= set(pediatric_pulmonology.inherits)
    assert any(
        membership.node_id == "population.pediatrics" and membership.config["priority_weight"] == 1
        for membership in pediatric_pulmonology.memberships
    )


def test_catalog_rejects_a_canonical_cycle():
    catalog = TaxonomyCatalog.load()
    catalog.edges.append(
        TaxonomyEdgeRecord(
            parent_id="disease.pulmonary_arterial_hypertension",
            child_id="disease.pulmonary_hypertension",
            edge_type="is_a",
            source="test",
            confidence=1,
            sort_order=0,
            metadata={},
        )
    )
    with pytest.raises(TaxonomyCatalogValidationError, match="cycle"):
        catalog.validate()


def test_generated_taxonomy_contracts_are_current():
    result = subprocess.run(
        [sys.executable, "scripts/generate_taxonomy_types.py", "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_catalog_install_is_idempotent_and_retires_without_losing_assignment(tmp_path):
    db = Database(tmp_path / "catalog.sqlite3", tmp_path / "backups")
    db.initialize()
    catalog = TaxonomyCatalog.load()
    catalog.install(db)
    first_counts = (
        db.scalar("SELECT COUNT(*) FROM taxonomy_nodes"),
        db.scalar("SELECT COUNT(*) FROM taxonomy_edges"),
        db.scalar("SELECT COUNT(*) FROM specialty_packs"),
    )
    catalog.install(db)
    assert first_counts == (
        db.scalar("SELECT COUNT(*) FROM taxonomy_nodes"),
        db.scalar("SELECT COUNT(*) FROM taxonomy_edges"),
        db.scalar("SELECT COUNT(*) FROM specialty_packs"),
    )
    assert db.scalar("SELECT COUNT(*) FROM taxonomy_catalog_versions") == 1
    db.execute(
        """
        INSERT INTO taxonomy_nodes(
            id, node_type, canonical_name, source_system, source_version,
            catalog_version
        ) VALUES (
            'disease.user_custom', 'disease', 'User custom concept', 'user',
            'local', 'taxonomy-v1'
        )
        """
    )
    db.execute(
        """
        INSERT INTO taxonomy_edges(
            parent_node_id, child_node_id, edge_type, source
        ) VALUES (
            'disease.copd', 'disease.user_custom', 'relevant_to', 'user'
        )
        """
    )

    db.execute(
        """
        INSERT INTO taxonomy_catalog_versions(version, source_date, content_sha256)
        VALUES ('taxonomy-v0', '2025-01-01', ?)
        """,
        ("0" * 64,),
    )
    db.execute(
        """
        INSERT INTO taxonomy_nodes(
            id, node_type, canonical_name, source_version, catalog_version
        ) VALUES (
            'disease.retired_example', 'disease', 'Retired example',
            'taxonomy-v0', 'taxonomy-v0'
        )
        """
    )
    document_id = int(
        db.execute(
            "INSERT INTO documents(title, normalized_title) VALUES (?, ?)",
            ("Catalog retirement test", "catalog retirement test"),
        ).lastrowid
    )
    db.execute(
        """
        INSERT INTO article_taxonomy_assignments(
            id, document_id, node_id, node_name_snapshot, node_type, role,
            source, verification_status, locked_by_user
        ) VALUES (
            'assignment-retained', ?, 'disease.retired_example',
            'Retired example', 'disease', 'primary_focus',
            'user', 'accepted', 1
        )
        """,
        (document_id,),
    )
    catalog.install(db)
    assert (
        db.scalar("SELECT status FROM taxonomy_nodes WHERE id = 'disease.user_custom'") == "active"
    )
    assert (
        db.scalar(
            """
            SELECT COUNT(*) FROM taxonomy_edges
            WHERE child_node_id = 'disease.user_custom' AND source = 'user'
            """
        )
        == 1
    )
    assert (
        db.scalar("SELECT status FROM taxonomy_nodes WHERE id = 'disease.retired_example'")
        == "retired"
    )
    assignment = db.fetch_one(
        "SELECT * FROM article_taxonomy_assignments WHERE id = 'assignment-retained'"
    )
    assert assignment is not None
    assert assignment["node_name_snapshot"] == "Retired example"

    catalog.manifest = catalog.manifest.model_copy(update={"content_sha256": "f" * 64})
    with pytest.raises(TaxonomyCatalogValidationError, match="different immutable"):
        catalog.install(db)


def test_read_only_catalog_apis_are_typed_paginated_and_feature_gated(tmp_path):
    settings = Settings(data_dir=tmp_path / "api-data", embedding_backend="hash")
    app = create_app(settings)
    with TestClient(app) as client:
        status = client.get("/api/v1/status")
        assert status.status_code == 200
        assert status.json()["schema_version"] == 8
        assert status.json()["taxonomy_profile_enabled"] is True
        assert status.json()["taxonomy_suggestions_enabled"] is False
        assert status.json()["taxonomy_auto_apply_enabled"] is False
        assert status.json()["taxonomy_disease_state_extraction_enabled"] is False
        page = client.get(
            "/api/v1/taxonomy/catalog",
            params={"query": "COPD", "node_type": "disease", "limit": 1},
        )
        assert page.status_code == 200
        assert page.json()["catalog_version"] == "taxonomy-v1"
        assert page.json()["total"] == 1
        assert page.json()["items"][0]["id"] == "disease.copd"

        child_page = client.get(
            "/api/v1/taxonomy/catalog",
            params={"parent": "disease.pulmonary_hypertension"},
        )
        assert child_page.status_code == 200
        assert {item["id"] for item in child_page.json()["items"]} == {
            "disease.cteph",
            "disease.pulmonary_arterial_hypertension",
        }
        assert client.get("/api/v1/taxonomy/catalog?limit=0").status_code == 422
        assert client.get("/api/v1/taxonomy/catalog?node_type=not_a_real_type").status_code == 422
        node = client.get("/api/v1/taxonomy/nodes/disease.copd")
        assert node.status_code == 200
        assert node.json()["source_version"] == "taxonomy-v1"
        assert client.get("/api/v1/taxonomy/nodes/disease.missing").status_code == 404
        packs = client.get("/api/v1/taxonomy/packs", params={"pack_type": "subspecialty"})
        assert packs.status_code == 200
        assert len(packs.json()) == 89
        tree = client.get("/api/v1/taxonomy/tree")
        assert tree.status_code == 200
        assert tree.json()["catalog_version"] == "taxonomy-v1"

    disabled = create_app(
        Settings(
            data_dir=tmp_path / "disabled-data",
            embedding_backend="hash",
            taxonomy_profile_enabled=False,
        )
    )
    with TestClient(disabled) as client:
        assert client.get("/api/v1/taxonomy/catalog").status_code == 404
