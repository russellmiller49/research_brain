from __future__ import annotations

import json
import uuid
from typing import Any

from research_memory.contracts import (
    BoundingBox,
    TaxonomyAssignment,
    TaxonomyAssignmentCreate,
    TaxonomyAssignmentUpdate,
    TaxonomyEvidence,
)
from research_memory.db import Database
from research_memory.services.taxonomy_catalog import (
    StateArchetypeRecord,
    TaxonomyCatalog,
)


class TaxonomyAssignmentError(ValueError):
    pass


class TaxonomyAssignmentService:
    def __init__(self, db: Database, catalog: TaxonomyCatalog):
        self.db = db
        self.catalog = catalog

    def list_for_article(self, article_id: int) -> list[TaxonomyAssignment]:
        rows = self.db.fetch_all(
            """
            SELECT * FROM article_taxonomy_assignments
            WHERE document_id = ? AND deleted_at IS NULL
            ORDER BY display_priority DESC, confidence DESC, created_at, id
            """,
            (article_id,),
        )
        return [self._to_assignment(row) for row in rows]

    def create(self, article_id: int, value: TaxonomyAssignmentCreate) -> TaxonomyAssignment:
        node = self.catalog.get_node(value.node_id)
        if node is None:
            raise TaxonomyAssignmentError(f"Taxonomy node does not resolve: {value.node_id}")
        self.validate_state(value.node_id, value.state)
        assignment_id = str(uuid.uuid4())
        with self.db.transaction() as connection:
            document = connection.execute(
                "SELECT id FROM documents WHERE id = ? AND deleted_at IS NULL",
                (article_id,),
            ).fetchone()
            if document is None:
                raise TaxonomyAssignmentError(f"Article does not exist: {article_id}")
            existing = connection.execute(
                """
                SELECT * FROM article_taxonomy_assignments
                WHERE document_id = ? AND node_id = ? AND role = ?
                """,
                (article_id, value.node_id, value.role),
            ).fetchone()
            if existing is not None:
                assignment_id = str(existing["id"])
            protected_human_decision = (
                existing is not None
                and value.source != "user"
                and (
                    bool(existing["locked_by_user"])
                    or str(existing["verification_status"])
                    in {"accepted", "rejected", "human_verified"}
                )
            )
            if not protected_human_decision:
                connection.execute(
                    """
                    INSERT INTO article_taxonomy_assignments(
                        id, document_id, node_id, node_name_snapshot, node_type,
                        role, confidence, source, verification_status, state_json,
                        locked_by_user, display_priority
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id, node_id, role) DO UPDATE SET
                        node_name_snapshot = excluded.node_name_snapshot,
                        node_type = excluded.node_type,
                        confidence = excluded.confidence,
                        source = excluded.source,
                        verification_status = excluded.verification_status,
                        state_json = excluded.state_json,
                        locked_by_user = excluded.locked_by_user,
                        display_priority = excluded.display_priority,
                        deleted_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        assignment_id,
                        article_id,
                        node.id,
                        node.canonical_name,
                        node.node_type,
                        value.role,
                        value.confidence,
                        value.source,
                        value.verification_status,
                        json.dumps(value.state, sort_keys=True, separators=(",", ":")),
                        int(value.locked_by_user),
                        value.display_priority,
                    ),
                )
                if value.evidence:
                    connection.execute(
                        "DELETE FROM article_taxonomy_evidence WHERE assignment_id = ?",
                        (assignment_id,),
                    )
                    self._insert_evidence(connection, assignment_id, value.evidence)
                self._history(
                    connection,
                    assignment_id=assignment_id,
                    article_id=article_id,
                    node_id=node.id,
                    action=(
                        "manual_assignment"
                        if value.source == "user"
                        else "derived_assignment_upsert"
                    ),
                    prior=dict(existing) if existing is not None else {},
                    new_value=value.model_dump(mode="json", exclude={"evidence"}),
                )
        result = self.get(assignment_id)
        if result is None:
            raise RuntimeError("Assignment write did not produce a row")
        return result

    def get(self, assignment_id: str) -> TaxonomyAssignment | None:
        row = self.db.fetch_one(
            """
            SELECT * FROM article_taxonomy_assignments
            WHERE id = ? AND deleted_at IS NULL
            """,
            (assignment_id,),
        )
        return None if row is None else self._to_assignment(row)

    def update(self, assignment_id: str, value: TaxonomyAssignmentUpdate) -> TaxonomyAssignment:
        existing = self.db.fetch_one(
            """
            SELECT * FROM article_taxonomy_assignments
            WHERE id = ? AND deleted_at IS NULL
            """,
            (assignment_id,),
        )
        if existing is None:
            raise TaxonomyAssignmentError("Taxonomy assignment not found")
        updates = value.model_dump(exclude_unset=True)
        if not updates:
            result = self.get(assignment_id)
            if result is None:
                raise RuntimeError("Assignment disappeared")
            return result
        if "state" in updates:
            self.validate_state(str(existing["node_id"]), updates["state"] or {})
            updates["state_json"] = json.dumps(
                updates.pop("state") or {}, sort_keys=True, separators=(",", ":")
            )
        if "locked_by_user" in updates:
            updates["locked_by_user"] = int(bool(updates["locked_by_user"]))
        allowed = {
            "role",
            "confidence",
            "verification_status",
            "state_json",
            "locked_by_user",
            "display_priority",
        }
        if set(updates) - allowed:
            raise TaxonomyAssignmentError("Unsupported assignment update")
        with self.db.transaction() as connection:
            assignments = ", ".join(f"{name} = ?" for name in updates)
            connection.execute(
                f"""
                UPDATE article_taxonomy_assignments
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*updates.values(), assignment_id),
            )
            self._history(
                connection,
                assignment_id=assignment_id,
                article_id=int(existing["document_id"]),
                node_id=str(existing["node_id"]),
                action=("reject" if updates.get("verification_status") == "rejected" else "update"),
                prior=dict(existing),
                new_value=value.model_dump(mode="json", exclude_unset=True),
            )
        result = self.get(assignment_id)
        if result is None:
            raise RuntimeError("Updated assignment disappeared")
        return result

    def validate_state(self, node_id: str, state: dict[str, Any]) -> None:
        if not state:
            return
        node = self.catalog.get_node(node_id)
        if node is None:
            raise TaxonomyAssignmentError(f"Taxonomy node does not resolve: {node_id}")
        archetype_ids = node.metadata.get("state_archetypes", [])
        archetypes: list[StateArchetypeRecord] = []
        for archetype_id in archetype_ids:
            archetype = self.catalog.state_archetypes_by_id.get(str(archetype_id))
            if archetype is not None:
                archetypes.append(archetype)
        dimensions = {
            dimension.id: dimension
            for archetype in archetypes
            for dimension in archetype.dimensions
        }
        unsupported = sorted(set(state) - set(dimensions))
        if unsupported:
            raise TaxonomyAssignmentError(
                f"Unsupported state dimensions for {node_id}: {unsupported}"
            )
        for dimension_id, state_value in state.items():
            value_type = dimensions[dimension_id].value_type
            valid = False
            if value_type in {"concept_or_text", "structured_text"}:
                valid = isinstance(state_value, (str, dict))
            elif value_type == "number":
                valid = isinstance(state_value, (int, float)) and not isinstance(state_value, bool)
            elif value_type == "boolean":
                valid = isinstance(state_value, bool)
            if not valid:
                raise TaxonomyAssignmentError(f"{dimension_id} requires value type {value_type}")

    def _to_assignment(self, row: Any) -> TaxonomyAssignment:
        evidence_rows = self.db.fetch_all(
            """
            SELECT * FROM article_taxonomy_evidence
            WHERE assignment_id = ? ORDER BY page_number, id
            """,
            (str(row["id"]),),
        )
        evidence = [
            TaxonomyEvidence(
                id=str(item["id"]),
                assignment_id=str(item["assignment_id"]),
                file_id=item["file_id"],
                page_number=item["page_number"],
                chunk_id=item["chunk_id"],
                supporting_text=str(item["supporting_text"]),
                bounding_boxes=[
                    BoundingBox.model_validate(box)
                    for box in json.loads(str(item["bounding_boxes_json"]))
                ],
                section_type=str(item["section_type"]),
                evidence_kind=str(item["evidence_kind"]),
                score=float(item["score"]),
                created_at=str(item["created_at"]),
            )
            for item in evidence_rows
        ]
        return TaxonomyAssignment.model_validate(
            {
                "id": str(row["id"]),
                "article_id": int(row["document_id"]),
                "node_id": str(row["node_id"]),
                "node_name_snapshot": str(row["node_name_snapshot"]),
                "node_type": str(row["node_type"]),
                "role": str(row["role"]),
                "confidence": float(row["confidence"]),
                "source": str(row["source"]),
                "verification_status": str(row["verification_status"]),
                "state": json.loads(str(row["state_json"])),
                "classifier_version": str(row["classifier_version"]),
                "input_fingerprint": str(row["input_fingerprint"]),
                "locked_by_user": bool(row["locked_by_user"]),
                "display_priority": int(row["display_priority"]),
                "evidence": evidence,
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
        )

    @staticmethod
    def _insert_evidence(
        connection: Any,
        assignment_id: str,
        evidence: list[TaxonomyEvidence],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO article_taxonomy_evidence(
                id, assignment_id, file_id, page_number, chunk_id,
                supporting_text, bounding_boxes_json, section_type,
                evidence_kind, score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    item.id or str(uuid.uuid4()),
                    assignment_id,
                    item.file_id,
                    item.page_number,
                    item.chunk_id,
                    item.supporting_text,
                    json.dumps(
                        [box.model_dump(mode="json") for box in item.bounding_boxes],
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    item.section_type,
                    item.evidence_kind,
                    item.score,
                )
                for item in evidence
            ),
        )

    @staticmethod
    def _history(
        connection: Any,
        *,
        assignment_id: str,
        article_id: int,
        node_id: str,
        action: str,
        prior: dict[str, Any],
        new_value: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO taxonomy_decision_history(
                id, assignment_id, document_id, node_id, action,
                prior_value_json, new_value_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                assignment_id,
                article_id,
                node_id,
                action,
                json.dumps(prior, sort_keys=True, default=str, separators=(",", ":")),
                json.dumps(new_value, sort_keys=True, default=str, separators=(",", ":")),
            ),
        )
