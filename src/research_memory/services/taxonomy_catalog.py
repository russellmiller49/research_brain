from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_memory.contracts import ExternalMapping
from research_memory.db import Database
from research_memory.generated.taxonomy_catalog import (
    PackCurationStatus,
    SpecialtyPackType,
    StateValueType,
    TaxonomyEdgeType,
    TaxonomyNodeStatus,
    TaxonomyNodeType,
)


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CatalogManifest(CatalogModel):
    catalog_version: str
    semantic_version: str
    source_date: str
    content_sha256: str
    files: list[str]
    starter_catalog: bool
    description: str


class TaxonomySource(CatalogModel):
    system: str
    source_id: str
    source_version: str


class TaxonomyNodeRecord(CatalogModel):
    id: str
    node_type: TaxonomyNodeType
    canonical_name: str
    description: str
    status: TaxonomyNodeStatus
    source: TaxonomySource
    external_mappings: list[ExternalMapping]
    metadata: dict[str, Any]


class CredentialSourceMetadata(CatalogModel):
    source_name: str
    source_type: str
    source_url: str
    retrieved_date: str
    expected_member_boards: int = Field(gt=0)
    expected_specialty_areas: int = Field(gt=0)
    expected_subspecialty_areas: int = Field(gt=0)
    source_notes: list[str]


class CredentialCatalog(CatalogModel):
    source_metadata: CredentialSourceMetadata
    nodes: list[TaxonomyNodeRecord]


class TaxonomySynonymRecord(CatalogModel):
    node_id: str
    synonym: str
    language_code: str
    source: str


class TaxonomyEdgeRecord(CatalogModel):
    parent_id: str
    child_id: str
    edge_type: TaxonomyEdgeType
    source: str
    confidence: float = Field(ge=0, le=1)
    sort_order: int
    metadata: dict[str, Any]


class PackMembershipRecord(CatalogModel):
    node_id: str
    membership_role: str
    display_parent_node_id: str | None
    sort_order: int
    config: dict[str, Any]


class SpecialtyPackRecord(CatalogModel):
    pack_id: str
    display_name: str
    pack_type: SpecialtyPackType
    version: str
    selection_node_id: str
    curation_status: PackCurationStatus
    inherits: list[str]
    memberships: list[PackMembershipRecord]
    state_archetypes: list[str]
    suggested_project_templates: list[str]


class StateDimensionRecord(CatalogModel):
    id: str
    display_name: str
    value_type: StateValueType
    required_evidence: bool


class StateArchetypeRecord(CatalogModel):
    id: str
    display_name: str
    version: str
    dimensions: list[StateDimensionRecord]


class TerminologyMappingProvider(Protocol):
    """Boundary for future optional terminology resolution.

    Phase 1 deliberately ships no network-backed implementation.
    """

    def lookup(self, node_id: str) -> list[ExternalMapping]: ...


class TaxonomyCatalogValidationError(ValueError):
    pass


def normalize_synonym(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())


def _load_json(path: Path) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise TaxonomyCatalogValidationError(f"{path}: duplicate JSON object key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise TaxonomyCatalogValidationError(f"Unable to read {path}: {exc}") from exc


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise TaxonomyCatalogValidationError(f"Unsupported JSON Schema type {expected!r}")


def _validate_json_schema(value: Any, schema: Mapping[str, Any], location: str) -> None:
    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = [expected_type] if isinstance(expected_type, str) else list(expected_type)
        if not any(_matches_json_type(value, item) for item in expected_types):
            raise TaxonomyCatalogValidationError(
                f"{location}: expected JSON type {expected_types}, got {type(value).__name__}"
            )

    if "enum" in schema and value not in schema["enum"]:
        raise TaxonomyCatalogValidationError(
            f"{location}: {value!r} is not one of {schema['enum']!r}"
        )

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [name for name in required if name not in value]
        if missing:
            raise TaxonomyCatalogValidationError(
                f"{location}: missing required properties {missing!r}"
            )
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                raise TaxonomyCatalogValidationError(f"{location}: unexpected properties {extra!r}")
        for name, child in value.items():
            if name in properties:
                _validate_json_schema(child, properties[name], f"{location}.{name}")

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        if minimum_items is not None and len(value) < int(minimum_items):
            raise TaxonomyCatalogValidationError(
                f"{location}: requires at least {minimum_items} items"
            )
        item_schema = schema.get("items")
        if item_schema:
            for index, child in enumerate(value):
                _validate_json_schema(child, item_schema, f"{location}[{index}]")

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if minimum_length is not None and len(value) < int(minimum_length):
            raise TaxonomyCatalogValidationError(
                f"{location}: requires at least {minimum_length} characters"
            )
        pattern = schema.get("pattern")
        if pattern and re.search(str(pattern), value) is None:
            raise TaxonomyCatalogValidationError(
                f"{location}: {value!r} does not match {pattern!r}"
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            raise TaxonomyCatalogValidationError(f"{location}: {value} is below minimum {minimum}")
        if maximum is not None and value > maximum:
            raise TaxonomyCatalogValidationError(f"{location}: {value} is above maximum {maximum}")


def _assert_acyclic(edges: Iterable[tuple[str, str]], *, graph_name: str) -> None:
    children: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for parent, child in edges:
        children[parent].add(child)
        nodes.update((parent, child))
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, trail: list[str]) -> None:
        if node in visiting:
            cycle_start = trail.index(node)
            cycle = " -> ".join([*trail[cycle_start:], node])
            raise TaxonomyCatalogValidationError(f"{graph_name} contains a cycle: {cycle}")
        if node in visited:
            return
        visiting.add(node)
        trail.append(node)
        for child in sorted(children[node]):
            visit(child, trail)
        trail.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(nodes):
        visit(node, [])


class TaxonomyCatalog:
    def __init__(
        self,
        *,
        root: Path,
        manifest: CatalogManifest,
        credential_source: CredentialSourceMetadata,
        nodes: list[TaxonomyNodeRecord],
        synonyms: list[TaxonomySynonymRecord],
        edges: list[TaxonomyEdgeRecord],
        packs: list[SpecialtyPackRecord],
        state_archetypes: list[StateArchetypeRecord],
    ):
        self.root = root
        self.manifest = manifest
        self.credential_source = credential_source
        self.nodes = nodes
        self.synonyms = synonyms
        self.edges = edges
        self.packs = packs
        self.state_archetypes = state_archetypes
        self.nodes_by_id = {node.id: node for node in nodes}
        self.packs_by_id = {pack.pack_id: pack for pack in packs}
        self.state_archetypes_by_id = {archetype.id: archetype for archetype in state_archetypes}

    @staticmethod
    def default_path() -> Path:
        return Path(__file__).resolve().parents[1] / "resources/taxonomy/v1"

    @classmethod
    def load(cls, root: str | Path | None = None) -> TaxonomyCatalog:
        catalog_root = Path(root) if root is not None else cls.default_path()
        catalog_root = catalog_root.resolve()
        schema_root = catalog_root.parent / "schemas/v1"
        manifest_data = _load_json(catalog_root / "catalog.json")
        manifest_schema = _load_json(schema_root / "catalog.schema.json")
        _validate_json_schema(manifest_data, manifest_schema, "catalog")
        try:
            manifest = CatalogManifest.model_validate(manifest_data)
        except ValidationError as exc:
            raise TaxonomyCatalogValidationError(f"catalog.json: {exc}") from exc

        if len(manifest.files) != len(set(manifest.files)):
            raise TaxonomyCatalogValidationError("catalog.json contains duplicate file paths")

        resolved_files: dict[str, Path] = {}
        for relative in manifest.files:
            path = (catalog_root / relative).resolve()
            try:
                path.relative_to(catalog_root)
            except ValueError as exc:
                raise TaxonomyCatalogValidationError(
                    f"Catalog file escapes its root: {relative}"
                ) from exc
            if not path.is_file():
                raise TaxonomyCatalogValidationError(
                    f"Catalog manifest file does not exist: {relative}"
                )
            resolved_files[relative] = path

        actual_files = {
            path.relative_to(catalog_root).as_posix()
            for path in catalog_root.rglob("*.json")
            if path != catalog_root / "catalog.json"
        }
        if actual_files != set(manifest.files):
            missing = sorted(set(manifest.files) - actual_files)
            unlisted = sorted(actual_files - set(manifest.files))
            raise TaxonomyCatalogValidationError(
                f"Catalog file manifest mismatch; missing={missing}, unlisted={unlisted}"
            )

        digest = hashlib.sha256()
        for relative in sorted(manifest.files):
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(resolved_files[relative].read_bytes())
            digest.update(b"\0")
        if digest.hexdigest() != manifest.content_sha256:
            raise TaxonomyCatalogValidationError("Catalog content hash does not match catalog.json")

        schema_by_kind = {
            "credential": _load_json(schema_root / "credential_catalog.schema.json"),
            "nodes": _load_json(schema_root / "nodes.schema.json"),
            "synonyms": _load_json(schema_root / "synonyms.schema.json"),
            "edges": _load_json(schema_root / "edges.schema.json"),
            "packs": _load_json(schema_root / "packs.schema.json"),
            "state": _load_json(schema_root / "state_archetype.schema.json"),
        }
        credential: CredentialCatalog | None = None
        nodes: list[TaxonomyNodeRecord] = []
        synonyms: list[TaxonomySynonymRecord] = []
        edges: list[TaxonomyEdgeRecord] = []
        packs: list[SpecialtyPackRecord] = []
        state_archetypes: list[StateArchetypeRecord] = []

        for relative in manifest.files:
            data = _load_json(resolved_files[relative])
            try:
                if relative == "credential_catalog.json":
                    _validate_json_schema(data, schema_by_kind["credential"], relative)
                    _validate_json_schema(
                        data["nodes"],
                        schema_by_kind["nodes"],
                        f"{relative}.nodes",
                    )
                    credential = CredentialCatalog.model_validate(data)
                    nodes.extend(credential.nodes)
                elif relative == "clinical_nodes.json":
                    _validate_json_schema(data, schema_by_kind["nodes"], relative)
                    nodes.extend(TaxonomyNodeRecord.model_validate(item) for item in data)
                elif relative == "synonyms.json":
                    _validate_json_schema(data, schema_by_kind["synonyms"], relative)
                    synonyms.extend(TaxonomySynonymRecord.model_validate(item) for item in data)
                elif relative == "edges.json":
                    _validate_json_schema(data, schema_by_kind["edges"], relative)
                    edges.extend(TaxonomyEdgeRecord.model_validate(item) for item in data)
                elif relative.startswith("packs/"):
                    _validate_json_schema(data, schema_by_kind["packs"], relative)
                    packs.extend(SpecialtyPackRecord.model_validate(item) for item in data)
                elif relative.startswith("state_archetypes/"):
                    _validate_json_schema(data, schema_by_kind["state"], relative)
                    state_archetypes.append(StateArchetypeRecord.model_validate(data))
                else:
                    raise TaxonomyCatalogValidationError(
                        f"No catalog schema routing rule for {relative}"
                    )
            except ValidationError as exc:
                raise TaxonomyCatalogValidationError(f"{relative}: {exc}") from exc

        if credential is None:
            raise TaxonomyCatalogValidationError("Credential catalog is required")
        result = cls(
            root=catalog_root,
            manifest=manifest,
            credential_source=credential.source_metadata,
            nodes=nodes,
            synonyms=synonyms,
            edges=edges,
            packs=packs,
            state_archetypes=state_archetypes,
        )
        result.validate()
        return result

    def validate(self) -> None:
        node_ids = [node.id for node in self.nodes]
        duplicate_nodes = sorted(
            node_id for node_id, count in Counter(node_ids).items() if count > 1
        )
        if duplicate_nodes:
            raise TaxonomyCatalogValidationError(
                f"Duplicate canonical node IDs: {duplicate_nodes[:10]}"
            )
        pack_ids = [pack.pack_id for pack in self.packs]
        duplicate_packs = sorted(
            pack_id for pack_id, count in Counter(pack_ids).items() if count > 1
        )
        if duplicate_packs:
            raise TaxonomyCatalogValidationError(f"Duplicate pack IDs: {duplicate_packs[:10]}")
        archetype_ids = [item.id for item in self.state_archetypes]
        if len(archetype_ids) != len(set(archetype_ids)):
            raise TaxonomyCatalogValidationError("Duplicate state archetype IDs")

        for node in self.nodes:
            if node.source.source_version != self.manifest.catalog_version:
                raise TaxonomyCatalogValidationError(
                    f"{node.id} source version does not match the catalog"
                )

        edge_keys: set[tuple[str, str, str]] = set()
        for edge in self.edges:
            if edge.parent_id not in self.nodes_by_id:
                raise TaxonomyCatalogValidationError(
                    f"Edge parent does not resolve: {edge.parent_id}"
                )
            if edge.child_id not in self.nodes_by_id:
                raise TaxonomyCatalogValidationError(
                    f"Edge child does not resolve: {edge.child_id}"
                )
            edge_key = (edge.parent_id, edge.child_id, edge.edge_type)
            if edge_key in edge_keys:
                raise TaxonomyCatalogValidationError(f"Duplicate edge: {edge_key}")
            edge_keys.add(edge_key)
        _assert_acyclic(
            (
                (edge.parent_id, edge.child_id)
                for edge in self.edges
                if edge.edge_type in {"is_a", "part_of"}
            ),
            graph_name="canonical taxonomy",
        )

        normalized_synonyms: set[tuple[str, str, str]] = set()
        for synonym in self.synonyms:
            if synonym.node_id not in self.nodes_by_id:
                raise TaxonomyCatalogValidationError(
                    f"Synonym node does not resolve: {synonym.node_id}"
                )
            normalized = normalize_synonym(synonym.synonym)
            if not normalized:
                raise TaxonomyCatalogValidationError("Synonym normalizes to an empty value")
            synonym_key = (synonym.node_id, normalized, synonym.language_code)
            if synonym_key in normalized_synonyms:
                raise TaxonomyCatalogValidationError(
                    f"Duplicate normalized synonym {normalized!r} for {synonym.node_id}"
                )
            normalized_synonyms.add(synonym_key)

        for pack in self.packs:
            if pack.selection_node_id not in self.nodes_by_id:
                raise TaxonomyCatalogValidationError(
                    f"{pack.pack_id} selection node does not resolve"
                )
            expected_selection_types = {
                "specialty": {"specialty"},
                "subspecialty": {"subspecialty"},
                "overlay": {"clinical_domain"},
                "focused_practice": {"focused_practice"},
                "research_methods": {"research_interest"},
            }
            selection_node = self.nodes_by_id[pack.selection_node_id]
            if selection_node.node_type not in expected_selection_types[pack.pack_type]:
                raise TaxonomyCatalogValidationError(
                    f"{pack.pack_id} has incompatible selection node type "
                    f"{selection_node.node_type}"
                )
            for inherited in pack.inherits:
                if inherited not in self.packs_by_id:
                    raise TaxonomyCatalogValidationError(
                        f"{pack.pack_id} inherits missing pack {inherited}"
                    )
            seen_memberships: set[tuple[str, str, str | None]] = set()
            membership_node_ids = {membership.node_id for membership in pack.memberships}
            for membership in pack.memberships:
                member_node = self.nodes_by_id.get(membership.node_id)
                if member_node is None:
                    raise TaxonomyCatalogValidationError(
                        f"{pack.pack_id} member does not resolve: {membership.node_id}"
                    )
                if member_node.status == "retired":
                    raise TaxonomyCatalogValidationError(
                        f"{pack.pack_id} includes retired node {membership.node_id}"
                    )
                if (
                    membership.display_parent_node_id is not None
                    and membership.display_parent_node_id not in self.nodes_by_id
                ):
                    raise TaxonomyCatalogValidationError(
                        f"{pack.pack_id} display parent does not resolve: "
                        f"{membership.display_parent_node_id}"
                    )
                if (
                    membership.display_parent_node_id is not None
                    and membership.display_parent_node_id
                    not in membership_node_ids | {pack.selection_node_id}
                ):
                    raise TaxonomyCatalogValidationError(
                        f"{pack.pack_id} display path cannot resolve through "
                        f"{membership.display_parent_node_id}"
                    )
                membership_key = (
                    membership.node_id,
                    membership.membership_role,
                    membership.display_parent_node_id,
                )
                if membership_key in seen_memberships:
                    raise TaxonomyCatalogValidationError(
                        f"{pack.pack_id} contains duplicate membership {membership_key}"
                    )
                seen_memberships.add(membership_key)
            reachable_display_nodes = {
                pack.selection_node_id,
                *(
                    membership.node_id
                    for membership in pack.memberships
                    if membership.display_parent_node_id is None
                ),
            }
            changed = True
            while changed:
                changed = False
                for membership in pack.memberships:
                    if (
                        membership.display_parent_node_id in reachable_display_nodes
                        and membership.node_id not in reachable_display_nodes
                    ):
                        reachable_display_nodes.add(membership.node_id)
                        changed = True
            unresolved_paths = sorted(
                {
                    membership.node_id
                    for membership in pack.memberships
                    if membership.node_id not in reachable_display_nodes
                }
            )
            if unresolved_paths:
                raise TaxonomyCatalogValidationError(
                    f"{pack.pack_id} contains unresolved display paths: {unresolved_paths[:10]}"
                )
            for archetype_id in pack.state_archetypes:
                if archetype_id not in self.state_archetypes_by_id:
                    raise TaxonomyCatalogValidationError(
                        f"{pack.pack_id} references missing state archetype {archetype_id}"
                    )
        _assert_acyclic(
            ((pack.pack_id, inherited) for pack in self.packs for inherited in pack.inherits),
            graph_name="pack inheritance",
        )

        for archetype in self.state_archetypes:
            for dimension in archetype.dimensions:
                dimension_node = self.nodes_by_id.get(dimension.id)
                if dimension_node is None or dimension_node.node_type != "state_dimension":
                    raise TaxonomyCatalogValidationError(
                        f"{archetype.id} dimension is not a state node: {dimension.id}"
                    )

        counts: Counter[str] = Counter(
            str(node.node_type) for node in self.nodes if node.source.system == "ABMS"
        )
        expected: dict[str, int] = {
            "certifying_board": self.credential_source.expected_member_boards,
            "specialty": self.credential_source.expected_specialty_areas,
            "subspecialty": self.credential_source.expected_subspecialty_areas,
        }
        for node_type, count in expected.items():
            if counts[node_type] != count:
                raise TaxonomyCatalogValidationError(
                    f"ABMS {node_type} count is {counts[node_type]}, expected {count}"
                )
        if self.credential_source.retrieved_date != self.manifest.source_date:
            raise TaxonomyCatalogValidationError(
                "Credential source date does not match catalog source date"
            )

        offered_children = {edge.child_id for edge in self.edges if edge.edge_type == "offered_by"}
        for node in self.nodes:
            if (
                node.source.system == "ABMS"
                and node.node_type in {"specialty", "subspecialty"}
                and node.id not in offered_children
            ):
                raise TaxonomyCatalogValidationError(
                    f"ABMS credential has no board offering edge: {node.id}"
                )
        pack_counts = Counter(pack.selection_node_id for pack in self.packs)
        for node in self.nodes:
            if node.node_type in {"specialty", "subspecialty"} and pack_counts[node.id] != 1:
                raise TaxonomyCatalogValidationError(
                    f"Credential node requires exactly one starter pack: {node.id}"
                )

    def get_node(self, node_id: str) -> TaxonomyNodeRecord | None:
        return self.nodes_by_id.get(node_id)

    def list_nodes(
        self,
        *,
        query: str = "",
        node_type: TaxonomyNodeType | None = None,
        parent_id: str | None = None,
    ) -> list[TaxonomyNodeRecord]:
        allowed_ids: set[str] | None = None
        if parent_id is not None:
            allowed_ids = {edge.child_id for edge in self.edges if edge.parent_id == parent_id}
        query_normalized = normalize_synonym(query)
        synonym_nodes = {
            synonym.node_id
            for synonym in self.synonyms
            if query_normalized and query_normalized in normalize_synonym(synonym.synonym)
        }
        result = []
        for node in self.nodes:
            if node_type is not None and node.node_type != node_type:
                continue
            if allowed_ids is not None and node.id not in allowed_ids:
                continue
            if query_normalized and (
                query_normalized not in normalize_synonym(node.canonical_name)
                and node.id not in synonym_nodes
            ):
                continue
            result.append(node)
        return sorted(result, key=lambda item: (item.canonical_name.casefold(), item.id))

    def list_packs(
        self, *, pack_type: SpecialtyPackType | None = None
    ) -> list[SpecialtyPackRecord]:
        return sorted(
            (pack for pack in self.packs if pack_type is None or pack.pack_type == pack_type),
            key=lambda item: (item.display_name.casefold(), item.pack_id),
        )

    def install(self, db: Database) -> None:
        with db.transaction() as connection:
            existing = connection.execute(
                """
                SELECT source_date, content_sha256
                FROM taxonomy_catalog_versions WHERE version = ?
                """,
                (self.manifest.catalog_version,),
            ).fetchone()
            if existing is not None and (
                str(existing["content_sha256"]) != self.manifest.content_sha256
                or str(existing["source_date"]) != self.manifest.source_date
            ):
                raise TaxonomyCatalogValidationError(
                    "Installed catalog version has different immutable source metadata"
                )
            connection.execute(
                """
                INSERT INTO taxonomy_catalog_versions(version, source_date, content_sha256)
                VALUES (?, ?, ?)
                ON CONFLICT(version) DO NOTHING
                """,
                (
                    self.manifest.catalog_version,
                    self.manifest.source_date,
                    self.manifest.content_sha256,
                ),
            )
            connection.execute("CREATE TEMP TABLE incoming_taxonomy_node_ids(id TEXT PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO incoming_taxonomy_node_ids(id) VALUES (?)",
                ((node.id,) for node in self.nodes),
            )
            connection.execute(
                """
                UPDATE taxonomy_nodes SET status = 'retired', updated_at = CURRENT_TIMESTAMP
                WHERE id NOT IN (SELECT id FROM incoming_taxonomy_node_ids)
                  AND source_system != 'user'
                """
            )
            for node in self.nodes:
                metadata = {
                    **node.metadata,
                    "external_mappings": node.external_mappings,
                }
                connection.execute(
                    """
                    INSERT INTO taxonomy_nodes(
                        id, node_type, canonical_name, description, status,
                        source_system, source_code, source_version,
                        metadata_json, catalog_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        node_type = excluded.node_type,
                        canonical_name = excluded.canonical_name,
                        description = excluded.description,
                        status = excluded.status,
                        source_system = excluded.source_system,
                        source_code = excluded.source_code,
                        source_version = excluded.source_version,
                        metadata_json = excluded.metadata_json,
                        catalog_version = excluded.catalog_version,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        node.id,
                        node.node_type,
                        node.canonical_name,
                        node.description,
                        node.status,
                        node.source.system,
                        node.source.source_id,
                        node.source.source_version,
                        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                        self.manifest.catalog_version,
                    ),
                )
            connection.execute(
                """
                DELETE FROM taxonomy_synonyms
                WHERE node_id IN (SELECT id FROM incoming_taxonomy_node_ids)
                """
            )
            connection.executemany(
                """
                INSERT INTO taxonomy_synonyms(
                    node_id, synonym, normalized_synonym, language_code, source
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        synonym.node_id,
                        synonym.synonym,
                        normalize_synonym(synonym.synonym),
                        synonym.language_code,
                        synonym.source,
                    )
                    for synonym in self.synonyms
                ),
            )
            connection.execute("DELETE FROM taxonomy_edges WHERE source != 'user'")
            connection.executemany(
                """
                INSERT INTO taxonomy_edges(
                    parent_node_id, child_node_id, edge_type, source,
                    confidence, sort_order, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        edge.parent_id,
                        edge.child_id,
                        edge.edge_type,
                        edge.source,
                        edge.confidence,
                        edge.sort_order,
                        json.dumps(edge.metadata, sort_keys=True, separators=(",", ":")),
                    )
                    for edge in self.edges
                ),
            )
            connection.execute("UPDATE specialty_packs SET active = 0")
            for pack in self.packs:
                connection.execute(
                    """
                    INSERT INTO specialty_packs(
                        pack_id, display_name, pack_type, selection_node_id,
                        version, curation_status, manifest_json, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(pack_id) DO UPDATE SET
                        display_name = excluded.display_name,
                        pack_type = excluded.pack_type,
                        selection_node_id = excluded.selection_node_id,
                        version = excluded.version,
                        curation_status = excluded.curation_status,
                        manifest_json = excluded.manifest_json,
                        active = 1
                    """,
                    (
                        pack.pack_id,
                        pack.display_name,
                        pack.pack_type,
                        pack.selection_node_id,
                        pack.version,
                        pack.curation_status,
                        pack.model_dump_json(),
                    ),
                )
                connection.execute(
                    "DELETE FROM specialty_pack_memberships WHERE pack_id = ?",
                    (pack.pack_id,),
                )
                connection.executemany(
                    """
                    INSERT INTO specialty_pack_memberships(
                        pack_id, node_id, membership_role,
                        display_parent_node_id, sort_order, config_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            pack.pack_id,
                            membership.node_id,
                            membership.membership_role,
                            membership.display_parent_node_id,
                            membership.sort_order,
                            json.dumps(
                                membership.config,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        )
                        for membership in pack.memberships
                    ),
                )
            connection.execute("DROP TABLE incoming_taxonomy_node_ids")
