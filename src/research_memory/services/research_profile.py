from __future__ import annotations

import json
import uuid

from research_memory.contracts import (
    NavigationOverride,
    ProfileSelection,
    ResearchProfile,
    ResearchProfileUpdate,
)
from research_memory.db import Database
from research_memory.services.taxonomy_catalog import TaxonomyCatalog


class ResearchProfileError(ValueError):
    pass


class ResearchProfileService:
    PROFILE_ID = 1
    _selection_node_types = {
        "primary_specialty": {"specialty"},
        "secondary_specialty": {"specialty"},
        "subspecialty": {"subspecialty"},
        "focused_practice": {"focused_practice"},
        "research_interest": {"research_interest"},
        "disease_interest": {"disease_family", "disease", "phenotype"},
        "clinical_activity": {
            "clinical_activity",
            "procedure",
            "diagnostic_test",
            "device_category",
        },
        "population_interest": {"population"},
        "work_product": {"work_product"},
        "evidence_priority": {"evidence_field", "methodology"},
    }

    def __init__(self, db: Database, catalog: TaxonomyCatalog):
        self.db = db
        self.catalog = catalog

    def default(self) -> ResearchProfile:
        return ResearchProfile(
            questionnaire_version="profile-v1",
            catalog_version=self.catalog.manifest.catalog_version,
        )

    def get(self) -> ResearchProfile | None:
        row = self.db.fetch_one("SELECT * FROM research_profile WHERE id = ?", (self.PROFILE_ID,))
        if row is None:
            return None
        selections = self.db.fetch_all(
            """
            SELECT node_id, relationship_type, priority_weight, visibility, source
            FROM research_profile_selections
            WHERE profile_id = ?
            ORDER BY relationship_type, priority_weight DESC, node_id
            """,
            (self.PROFILE_ID,),
        )
        preference_rows = self.db.fetch_all(
            """
            SELECT key, value_json FROM research_profile_preferences
            WHERE profile_id = ? ORDER BY key
            """,
            (self.PROFILE_ID,),
        )
        override_rows = self.db.fetch_all(
            """
            SELECT id, node_id, action, display_parent_node_id,
                   display_alias, sort_order
            FROM user_navigation_overrides
            WHERE profile_id = ? ORDER BY sort_order, id
            """,
            (self.PROFILE_ID,),
        )
        return ResearchProfile.model_validate(
            {
                "id": 1,
                "role_type": str(row["role_type"]),
                "automation_mode": str(row["automation_mode"]),
                "hierarchy_depth": str(row["hierarchy_depth"]),
                "questionnaire_version": str(row["questionnaire_version"]),
                "raw_answers": json.loads(str(row["raw_answers_json"])),
                "catalog_version": str(row["catalog_version"]),
                "onboarding_completed": bool(row["onboarding_completed"]),
                "selections": [ProfileSelection.model_validate(dict(item)) for item in selections],
                "preferences": {
                    str(item["key"]): json.loads(str(item["value_json"]))
                    for item in preference_rows
                },
                "navigation_overrides": [
                    NavigationOverride.model_validate(dict(item)) for item in override_rows
                ],
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
        )

    def get_or_default(self) -> ResearchProfile:
        return self.get() or self.default()

    def save(self, update: ResearchProfileUpdate) -> ResearchProfile:
        self._validate(update)
        try:
            raw_answers_json = json.dumps(update.raw_answers, sort_keys=True, separators=(",", ":"))
            preference_values = [
                (
                    key,
                    json.dumps(value, sort_keys=True, separators=(",", ":")),
                )
                for key, value in sorted(update.preferences.items())
            ]
        except (TypeError, ValueError) as exc:
            raise ResearchProfileError(
                "Profile answers and preferences must be JSON serializable"
            ) from exc

        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO research_profile(
                    id, role_type, automation_mode, hierarchy_depth,
                    questionnaire_version, raw_answers_json, catalog_version,
                    onboarding_completed
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    role_type = excluded.role_type,
                    automation_mode = excluded.automation_mode,
                    hierarchy_depth = excluded.hierarchy_depth,
                    questionnaire_version = excluded.questionnaire_version,
                    raw_answers_json = excluded.raw_answers_json,
                    catalog_version = excluded.catalog_version,
                    onboarding_completed = excluded.onboarding_completed,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    update.role_type,
                    update.automation_mode,
                    update.hierarchy_depth,
                    update.questionnaire_version,
                    raw_answers_json,
                    update.catalog_version,
                    int(update.onboarding_completed),
                ),
            )
            connection.execute("DELETE FROM research_profile_selections WHERE profile_id = 1")
            connection.executemany(
                """
                INSERT INTO research_profile_selections(
                    profile_id, node_id, relationship_type,
                    priority_weight, visibility, source
                ) VALUES (1, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        selection.node_id,
                        selection.relationship_type,
                        selection.priority_weight,
                        selection.visibility,
                        selection.source,
                    )
                    for selection in update.selections
                ),
            )
            connection.execute("DELETE FROM research_profile_preferences WHERE profile_id = 1")
            connection.executemany(
                """
                INSERT INTO research_profile_preferences(profile_id, key, value_json)
                VALUES (1, ?, ?)
                """,
                preference_values,
            )
            connection.execute("DELETE FROM user_navigation_overrides WHERE profile_id = 1")
            connection.executemany(
                """
                INSERT INTO user_navigation_overrides(
                    id, profile_id, node_id, action, display_parent_node_id,
                    display_alias, sort_order
                ) VALUES (?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        override.id or self._override_id(override),
                        override.node_id,
                        override.action,
                        override.display_parent_node_id,
                        override.display_alias,
                        override.sort_order,
                    )
                    for override in update.navigation_overrides
                ),
            )
        result = self.get()
        if result is None:
            raise RuntimeError("Profile save did not produce a profile row")
        return result

    def complete(self) -> ResearchProfile:
        profile = self.get()
        if profile is None:
            raise ResearchProfileError("Save the profile draft before completing it")
        self.db.execute(
            """
            UPDATE research_profile
            SET onboarding_completed = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """
        )
        result = self.get()
        if result is None:
            raise RuntimeError("Completed profile disappeared")
        return result

    def _validate(self, update: ResearchProfileUpdate) -> None:
        if update.catalog_version != self.catalog.manifest.catalog_version:
            raise ResearchProfileError(
                f"Profile catalog version must be {self.catalog.manifest.catalog_version}"
            )
        selection_keys: set[tuple[str, str]] = set()
        primary_specialties = 0
        for selection in update.selections:
            node = self.catalog.get_node(selection.node_id)
            if node is None or node.status == "retired":
                raise ResearchProfileError(
                    f"Profile selection is not an active catalog node: {selection.node_id}"
                )
            allowed_node_types = self._selection_node_types[selection.relationship_type]
            if node.node_type not in allowed_node_types:
                raise ResearchProfileError(
                    f"{selection.relationship_type} does not accept "
                    f"{node.node_type} node {selection.node_id}"
                )
            selection_key = (selection.node_id, selection.relationship_type)
            if selection_key in selection_keys:
                raise ResearchProfileError(f"Duplicate profile selection: {selection_key}")
            selection_keys.add(selection_key)
            primary_specialties += int(selection.relationship_type == "primary_specialty")
        if primary_specialties > 1:
            raise ResearchProfileError("Only one primary specialty may be selected")

        override_keys: set[tuple[str, str, str | None]] = set()
        for override in update.navigation_overrides:
            if self.catalog.get_node(override.node_id) is None:
                raise ResearchProfileError(
                    f"Navigation override node does not resolve: {override.node_id}"
                )
            if (
                override.display_parent_node_id is not None
                and self.catalog.get_node(override.display_parent_node_id) is None
            ):
                raise ResearchProfileError(
                    "Navigation override display parent does not resolve: "
                    f"{override.display_parent_node_id}"
                )
            override_key = (
                override.node_id,
                override.action,
                override.display_parent_node_id,
            )
            if override_key in override_keys:
                raise ResearchProfileError(f"Duplicate navigation override: {override_key}")
            override_keys.add(override_key)

    @staticmethod
    def _override_id(override: NavigationOverride) -> str:
        stable = "|".join(
            (
                override.node_id,
                override.action,
                override.display_parent_node_id or "",
                override.display_alias,
                str(override.sort_order),
            )
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"research-memory:{stable}"))
