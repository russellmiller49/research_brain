from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_memory.generated.taxonomy_catalog import (
    AssignmentRole,
    AssignmentSource,
    AutomationMode,
    ExternalVocabulary,
    HierarchyDepth,
    MappingStatus,
    NavigationOverrideAction,
    PackCurationStatus,
    ProfileRelationshipType,
    SpecialtyPackType,
    TaxonomyEdgeType,
    TaxonomyNodeStatus,
    TaxonomyNodeType,
    VerificationStatus,
)


class ContractModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class BoundingBox(ContractModel):
    """A rectangle in PDF user-space points with a bottom-left origin."""

    x0: float
    y0: float
    x1: float
    y1: float
    coordinate_space: Literal["pdf_points"] = "pdf_points"


class MatchReason(ContractModel):
    code: str
    label: str


class SearchQuery(ContractModel):
    text: str = Field(min_length=1, max_length=2_000)
    year_min: int | None = None
    year_max: int | None = None
    source_type: str | None = None
    reading_status: str | None = None
    project_id: int | None = None
    document_ids: list[int] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class SearchHit(ContractModel):
    rank: int
    article_id: int
    asset_id: int | None
    title: str
    authors: str
    journal: str
    publication_year: int | None
    source_type: str
    page_number: int | None
    passage_id: int | None
    snippet: str
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    match_reasons: list[MatchReason] = Field(default_factory=list)
    why_saved: str = ""


JobStatus = Literal["queued", "running", "paused", "succeeded", "failed", "canceled"]


class ImportJob(ContractModel):
    id: str
    type: str
    source: str
    stage: str
    status: JobStatus
    progress_current: int
    progress_total: int
    progress: float
    retryable: bool
    error_code: str | None = None
    issue_count: int = 0
    created_at: datetime | str
    updated_at: datetime | str


class ImportIssue(ContractModel):
    id: int
    job_id: str
    source_label: str
    error_code: str
    retryable: bool
    created_at: datetime | str


AnnotationType = Literal["highlight", "comment", "bookmark"]


class AnnotationCreate(ContractModel):
    asset_id: int
    page_number: int = Field(ge=1)
    annotation_type: AnnotationType
    color: str = Field(default="#F4C95D", pattern=r"^#[0-9A-Fa-f]{6}$")
    quad_points: list[float] = Field(default_factory=list)
    selected_text: str = Field(default="", max_length=20_000)
    context_hash: str = Field(default="", max_length=128)
    comment: str = Field(default="", max_length=50_000)


class Annotation(AnnotationCreate):
    id: str
    article_id: int
    created_at: datetime | str
    updated_at: datetime | str


class ArticleAsset(ContractModel):
    id: int
    article_id: int
    sha256: str
    file_name: str
    role: str
    version_label: str
    source_kind: str
    availability: str
    is_primary: bool
    size_bytes: int


class ArticleSummary(ContractModel):
    id: int
    title: str
    authors: str
    journal: str
    publication_year: int | None
    source_type: str
    reading_status: str
    importance: int
    page_count: int
    why_saved: str
    extraction_status: str
    review_state: str


class ArticlePage(ContractModel):
    items: list[ArticleSummary]
    total: int
    limit: int
    offset: int


class TrashArticle(ContractModel):
    id: int
    title: str
    deleted_at: datetime | str
    purge_after: datetime | str


class ArticleDetail(ArticleSummary):
    doi: str
    pmid: str
    abstract: str
    user_summary: str
    metadata_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    assets: list[ArticleAsset] = Field(default_factory=list)
    annotations: list[Annotation] = Field(default_factory=list)


class ImportPathRequest(ContractModel):
    path: str
    recursive: bool = True
    watch: bool = True
    project_id: int | None = None
    source_kind: Literal["folder", "file"] = "folder"


class ZoteroSyncRequest(ContractModel):
    base_url: Literal["http://127.0.0.1:23119/api"] = "http://127.0.0.1:23119/api"


class AssetAccess(ContractModel):
    url: str
    expires_at: datetime | str


class TaxonomyNodeSummary(ContractModel):
    id: str
    node_type: TaxonomyNodeType
    canonical_name: str
    status: TaxonomyNodeStatus


class ExternalMapping(ContractModel):
    vocabulary: ExternalVocabulary
    code: str
    display_name: str = ""
    version: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    status: MappingStatus


class TaxonomyNode(TaxonomyNodeSummary):
    description: str
    source_system: str
    source_code: str
    source_version: str
    external_mappings: list[ExternalMapping] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaxonomyCatalogPage(ContractModel):
    items: list[TaxonomyNodeSummary]
    total: int
    limit: int
    offset: int
    catalog_version: str


class TaxonomyEdge(ContractModel):
    parent_id: str
    child_id: str
    edge_type: TaxonomyEdgeType
    source: str
    confidence: float = Field(ge=0, le=1)
    sort_order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpecialtyPackSummary(ContractModel):
    pack_id: str
    display_name: str
    pack_type: SpecialtyPackType
    version: str
    selection_node_id: str
    curation_status: PackCurationStatus
    inherits: list[str] = Field(default_factory=list)
    membership_count: int = Field(ge=0)
    state_archetypes: list[str] = Field(default_factory=list)


class ProfileSelection(ContractModel):
    node_id: str
    relationship_type: ProfileRelationshipType
    priority_weight: float = Field(default=0.5, ge=0, le=1)
    visibility: str = Field(default="normal", max_length=100)
    source: str = Field(default="user", max_length=100)


class NavigationOverride(ContractModel):
    id: str | None = None
    node_id: str
    action: NavigationOverrideAction
    display_parent_node_id: str | None = None
    display_alias: str = Field(default="", max_length=500)
    sort_order: int = 0


class ResearchProfile(ContractModel):
    id: Literal[1] = 1
    role_type: str = Field(default="physician_researcher", max_length=100)
    automation_mode: AutomationMode = "balanced"
    hierarchy_depth: HierarchyDepth = "balanced"
    questionnaire_version: str
    raw_answers: dict[str, Any] = Field(default_factory=dict)
    catalog_version: str
    onboarding_completed: bool = False
    selections: list[ProfileSelection] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)
    navigation_overrides: list[NavigationOverride] = Field(default_factory=list)
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class ResearchProfileUpdate(ContractModel):
    role_type: str = Field(default="physician_researcher", max_length=100)
    automation_mode: AutomationMode = "balanced"
    hierarchy_depth: HierarchyDepth = "balanced"
    questionnaire_version: str = "profile-v1"
    raw_answers: dict[str, Any] = Field(default_factory=dict)
    catalog_version: str
    onboarding_completed: bool = False
    selections: list[ProfileSelection] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)
    navigation_overrides: list[NavigationOverride] = Field(default_factory=list)


class PersonalizedTaxonomyNode(ContractModel):
    canonical_node_id: str
    display_instance_id: str
    parent_display_instance_id: str | None = None
    display_name: str
    node_type: TaxonomyNodeType
    weight: float = Field(ge=0, le=1)
    depth: int = Field(ge=0)
    visible: bool = True
    pinned: bool = False
    children: list[PersonalizedTaxonomyNode] = Field(default_factory=list)


class PersonalizedTaxonomyTree(ContractModel):
    catalog_version: str
    profile_revision: str
    warnings: list[str] = Field(default_factory=list)
    roots: list[PersonalizedTaxonomyNode] = Field(default_factory=list)
    total_canonical_nodes: int = Field(ge=0)


class TaxonomyEvidence(ContractModel):
    id: str
    assignment_id: str
    file_id: int | None = None
    page_number: int | None = Field(default=None, ge=1)
    chunk_id: int | None = None
    supporting_text: str = Field(default="", max_length=2_000)
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)
    section_type: str = "unknown"
    evidence_kind: str
    score: float = Field(default=0, ge=0, le=1)
    created_at: datetime | str | None = None


class TaxonomyAssignment(ContractModel):
    id: str
    article_id: int
    node_id: str
    node_name_snapshot: str
    node_type: TaxonomyNodeType
    role: AssignmentRole
    confidence: float = Field(ge=0, le=1)
    source: AssignmentSource
    verification_status: VerificationStatus
    state: dict[str, Any] = Field(default_factory=dict)
    classifier_version: str = ""
    input_fingerprint: str = ""
    locked_by_user: bool = False
    display_priority: int = 0
    evidence: list[TaxonomyEvidence] = Field(default_factory=list)
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class TaxonomyAssignmentCreate(ContractModel):
    node_id: str
    role: AssignmentRole
    confidence: float = Field(default=1, ge=0, le=1)
    source: AssignmentSource = "user"
    verification_status: VerificationStatus = "accepted"
    state: dict[str, Any] = Field(default_factory=dict)
    locked_by_user: bool = True
    display_priority: int = 0
    evidence: list[TaxonomyEvidence] = Field(default_factory=list)


class TaxonomyAssignmentUpdate(ContractModel):
    role: AssignmentRole | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    verification_status: VerificationStatus | None = None
    state: dict[str, Any] | None = None
    locked_by_user: bool | None = None
    display_priority: int | None = None


class TaxonomyReviewItem(ContractModel):
    assignment: TaxonomyAssignment
    article: ArticleSummary


class TaxonomyReviewPage(ContractModel):
    items: list[TaxonomyReviewItem]
    total: int
    limit: int
    offset: int
    classifier_versions: list[str] = Field(default_factory=list)


class TaxonomyFacet(ContractModel):
    node_id: str
    display_name: str
    node_type: TaxonomyNodeType
    count: int = Field(ge=0)


class TaxonomyFacetResponse(ContractModel):
    items: list[TaxonomyFacet]
    total_documents: int = Field(ge=0)


class TaxonomyClassificationRequest(ContractModel):
    force: bool = False


class TaxonomyBulkDecisionRequest(ContractModel):
    assignment_ids: list[str] = Field(min_length=1, max_length=10_000)
    decision: Literal["accept", "reject"]
    reason: str = Field(default="", max_length=2_000)
