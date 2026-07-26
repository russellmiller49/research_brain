from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
