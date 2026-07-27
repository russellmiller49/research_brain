from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_memory.contracts import (
    BoundingBox,
    TaxonomyAssignmentCreate,
    TaxonomyAssignmentUpdate,
    TaxonomyEvidence,
)
from research_memory.db import Database
from research_memory.services.taxonomy_assignments import (
    TaxonomyAssignmentError,
    TaxonomyAssignmentService,
)
from research_memory.services.taxonomy_catalog import TaxonomyCatalog


@pytest.fixture
def assignment_services(tmp_path):
    db = Database(tmp_path / "assignments.sqlite3", tmp_path / "backups")
    db.initialize()
    catalog = TaxonomyCatalog.load()
    catalog.install(db)
    article_id = int(
        db.execute(
            "INSERT INTO documents(title, normalized_title) VALUES (?, ?)",
            ("Manual taxonomy test", "manual taxonomy test"),
        ).lastrowid
    )
    return db, TaxonomyAssignmentService(db, catalog), article_id


def test_manual_assignment_evidence_edit_and_retained_rejection(assignment_services):
    db, service, article_id = assignment_services
    assignment = service.create(
        article_id,
        TaxonomyAssignmentCreate(
            node_id="disease.copd",
            role="primary_focus",
            state={"state.severity": "severe"},
            evidence=[
                TaxonomyEvidence(
                    id="evidence-1",
                    assignment_id="replaced-by-service",
                    page_number=1,
                    supporting_text="Severe COPD was the central study condition.",
                    bounding_boxes=[BoundingBox(x0=10, y0=20, x1=40, y1=50)],
                    evidence_kind="manual",
                    score=1,
                )
            ],
        ),
    )
    assert assignment.source == "user"
    assert assignment.verification_status == "accepted"
    assert assignment.locked_by_user is True
    assert assignment.state == {"state.severity": "severe"}
    assert assignment.evidence[0].assignment_id == assignment.id

    repeated = service.create(
        article_id,
        TaxonomyAssignmentCreate(
            node_id="disease.copd",
            role="primary_focus",
            state={"state.severity": "moderate"},
        ),
    )
    assert repeated.id == assignment.id
    assert (
        db.scalar(
            """
            SELECT COUNT(*) FROM article_taxonomy_assignments
            WHERE document_id = ? AND node_id = 'disease.copd'
            """,
            (article_id,),
        )
        == 1
    )
    protected = service.create(
        article_id,
        TaxonomyAssignmentCreate(
            node_id="disease.copd",
            role="primary_focus",
            confidence=0.51,
            source="classifier",
            verification_status="suggested",
            state={},
            locked_by_user=False,
        ),
    )
    assert protected.id == assignment.id
    assert protected.source == "user"
    assert protected.locked_by_user is True
    rejected = service.update(
        assignment.id,
        TaxonomyAssignmentUpdate(
            verification_status="rejected",
            locked_by_user=True,
        ),
    )
    assert rejected.verification_status == "rejected"
    assert service.get(assignment.id) is not None
    assert (
        db.scalar(
            """
            SELECT COUNT(*) FROM taxonomy_decision_history
            WHERE assignment_id = ? AND action = 'reject'
            """,
            (assignment.id,),
        )
        == 1
    )


def test_assignment_role_and_state_archetype_validation(assignment_services):
    _, service, article_id = assignment_services
    with pytest.raises(ValidationError):
        TaxonomyAssignmentCreate(
            node_id="disease.copd",
            role="made_up_role",
        )
    with pytest.raises(TaxonomyAssignmentError, match="Unsupported state"):
        service.create(
            article_id,
            TaxonomyAssignmentCreate(
                node_id="disease.copd",
                role="primary_focus",
                state={"state.histology": "adenocarcinoma"},
            ),
        )
    with pytest.raises(TaxonomyAssignmentError, match="requires value type number"):
        service.create(
            article_id,
            TaxonomyAssignmentCreate(
                node_id="disease.ards",
                role="primary_focus",
                state={"state.mortality_or_functional_outcome_timepoint": ("not a number")},
            ),
        )


def test_profile_changes_cannot_alter_truth_and_article_delete_cascades(
    assignment_services,
):
    db, service, article_id = assignment_services
    assignment = service.create(
        article_id,
        TaxonomyAssignmentCreate(
            node_id="disease.pulmonary_hypertension",
            role="primary_focus",
        ),
    )
    db.execute(
        """
        UPDATE taxonomy_nodes SET canonical_name = 'Renamed after catalog update',
                                  status = 'retired'
        WHERE id = 'disease.pulmonary_hypertension'
        """
    )
    retained = service.get(assignment.id)
    assert retained is not None
    assert retained.node_name_snapshot == "Pulmonary hypertension"
    db.execute("DELETE FROM documents WHERE id = ?", (article_id,))
    assert service.get(assignment.id) is None
    assert (
        db.scalar(
            "SELECT COUNT(*) FROM taxonomy_decision_history WHERE document_id = ?",
            (article_id,),
        )
        == 0
    )
