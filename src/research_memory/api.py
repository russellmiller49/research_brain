from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, SecretStr
from starlette.background import BackgroundTask

from research_memory.contracts import (
    Annotation,
    AnnotationCreate,
    ArticleAsset,
    ArticleDetail,
    ArticlePage,
    ArticleSummary,
    ImportIssue,
    ImportJob,
    ImportPathRequest,
    MatchReason,
    SearchHit,
    SearchQuery,
    TrashArticle,
    ZoteroSyncRequest,
)
from research_memory.services.backup import BackupError
from research_memory.services.export import documents_to_bibtex, documents_to_ris
from research_memory.services.jobs import JobsBusy
from research_memory.services.search import SearchFilters
from research_memory.utils import normalize_title, safe_filename

router = APIRouter(prefix="/api/v1")


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArticleUpdate(StrictInput):
    title: str | None = Field(default=None, max_length=1_000)
    authors: str | None = Field(default=None, max_length=2_000)
    journal: str | None = Field(default=None, max_length=500)
    publication_year: int | None = Field(default=None, ge=1500, le=2200)
    doi: str | None = Field(default=None, max_length=500)
    pmid: str | None = Field(default=None, max_length=20)
    reading_status: str | None = None
    importance: int | None = Field(default=None, ge=0, le=5)
    why_saved: str | None = Field(default=None, max_length=50_000)
    user_summary: str | None = Field(default=None, max_length=100_000)


class ProjectCreate(StrictInput):
    name: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=50_000)
    project_type: Literal[
        "collection",
        "manuscript",
        "systematic_review",
        "guideline",
        "lecture",
        "curriculum",
        "grant",
        "journal_club",
    ] = "collection"


class BackupRequest(StrictInput):
    destination: str
    passphrase: str = Field(min_length=12, max_length=1_024)


class RestoreRequest(StrictInput):
    source: str
    passphrase: str = Field(min_length=12, max_length=1_024)


class SupportBundleRequest(StrictInput):
    destination: str


class ModelInstallRequest(StrictInput):
    consent_to_download: bool


class ProjectArticleUpdate(StrictInput):
    status: Literal[
        "candidate",
        "to_review",
        "included",
        "excluded",
        "background",
        "data_extracted",
        "ready_for_synthesis",
    ] = "candidate"


class ProjectArticlesBulkAdd(StrictInput):
    article_ids: list[PositiveInt] = Field(min_length=1, max_length=10_000)


class ProjectArticlesBulkResult(BaseModel):
    project_id: int
    requested: int
    added: int
    already_present: int


class PrivacySettingsUpdate(StrictInput):
    enable_network_metadata: bool | None = None
    diagnostics_enabled: bool | None = None


class PasswordUnlockRequest(StrictInput):
    password: SecretStr = Field(min_length=1, max_length=1_024)


class ReviewResolution(StrictInput):
    resolution: Literal["accept_as_separate_article", "keep_as_single_article"]


def _state(request: Request, name: str) -> Any:
    return getattr(request.app.state, name)


def _asset(row: Any) -> ArticleAsset:
    return ArticleAsset(
        id=int(row["id"]),
        article_id=int(row["document_id"]),
        sha256=row["sha256"],
        file_name=row["file_name"],
        role=row["role"],
        version_label=row["version_label"],
        source_kind=row["source_kind"],
        availability=row["availability"],
        is_primary=bool(row["is_primary"]),
        size_bytes=int(row["size_bytes"]),
    )


def _summary(row: Any) -> ArticleSummary:
    return ArticleSummary(
        id=int(row["id"]),
        title=row["title"],
        authors=row["authors"],
        journal=row["journal"],
        publication_year=row["publication_year"],
        source_type=row["source_type"],
        reading_status=row["reading_status"],
        importance=int(row["importance"]),
        page_count=int(row["page_count"]),
        why_saved=row["why_saved"],
        extraction_status=row["extraction_status"],
        review_state=row["review_state"],
    )


def _export_asset(db: Any, article_id: int, asset_id: int | None) -> Any:
    parameters: list[int] = [article_id]
    asset_clause = ""
    if asset_id is not None:
        asset_clause = "AND f.id = ?"
        parameters.append(asset_id)
    row = db.fetch_one(
        f"""
        SELECT f.* FROM document_files f
        JOIN documents d ON d.id = f.document_id
        WHERE f.document_id = ? AND f.availability = 'available'
          AND d.deleted_at IS NULL {asset_clause}
        ORDER BY f.is_primary DESC, f.id LIMIT 1
        """,
        parameters,
    )
    if not row:
        raise HTTPException(404, "Article asset not found")
    return row


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    db = _state(request, "db")
    settings = _state(request, "settings")
    embedder = _state(request, "embedder")
    return {
        "status": "ok",
        "version": "0.2.0",
        "schema_version": db.schema_version,
        "documents": int(db.scalar("SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL") or 0),
        "review_needed": int(
            db.scalar(
                """
                SELECT COUNT(*) FROM documents
                WHERE deleted_at IS NULL
                  AND (
                    review_state != 'ready'
                    OR extraction_status IN ('partial', 'needs_ocr', 'reindex_required')
                  )
                """
            )
            or 0
        ),
        "jobs_running": int(db.scalar("SELECT COUNT(*) FROM jobs WHERE status = 'running'") or 0),
        "embedding_backend": embedder.backend_name,
        "embedding_warning": embedder.warning,
        "ocr_available": bool(settings.resolved_tesseract_path),
        "network_metadata_enabled": settings.enable_network_metadata,
        "diagnostics_enabled": settings.diagnostics_enabled,
    }


@router.get("/articles", response_model=list[ArticleSummary])
async def list_articles(
    request: Request,
    query: str = "",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ArticleSummary]:
    db = _state(request, "db")
    parameters: list[Any] = []
    where = "deleted_at IS NULL"
    if query.strip():
        pattern = f"%{query.strip().lower()}%"
        where += " AND (lower(title) LIKE ? OR lower(authors) LIKE ?)"
        parameters.extend([pattern, pattern])
    parameters.extend([limit, offset])
    rows = db.fetch_all(
        f"""
        SELECT * FROM documents WHERE {where}
        ORDER BY created_at DESC LIMIT ? OFFSET ?
        """,
        parameters,
    )
    return [_summary(row) for row in rows]


@router.get("/articles/page", response_model=ArticlePage)
async def list_article_page(
    request: Request,
    query: str = "",
    limit: int = Query(100, ge=1, le=250),
    offset: int = Query(0, ge=0),
) -> ArticlePage:
    db = _state(request, "db")
    parameters: list[Any] = []
    where = "deleted_at IS NULL"
    if query.strip():
        pattern = f"%{query.strip().lower()}%"
        where += (
            " AND (lower(title) LIKE ? OR lower(authors) LIKE ?"
            " OR lower(journal) LIKE ? OR lower(doi) LIKE ? OR lower(pmid) LIKE ?)"
        )
        parameters.extend([pattern] * 5)
    total = int(db.scalar(f"SELECT COUNT(*) FROM documents WHERE {where}", parameters) or 0)
    rows = db.fetch_all(
        f"""
        SELECT * FROM documents WHERE {where}
        ORDER BY created_at DESC LIMIT ? OFFSET ?
        """,
        [*parameters, limit, offset],
    )
    return ArticlePage(
        items=[_summary(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/articles/{article_id}", response_model=ArticleDetail)
async def get_article(request: Request, article_id: int) -> ArticleDetail:
    db = _state(request, "db")
    row = db.fetch_one("SELECT * FROM documents WHERE id = ? AND deleted_at IS NULL", (article_id,))
    if not row:
        raise HTTPException(404, "Article not found")
    assets = db.fetch_all(
        """
        SELECT * FROM document_files WHERE document_id = ?
        ORDER BY is_primary DESC, id
        """,
        (article_id,),
    )
    annotations = _state(request, "annotations").list_for_document(article_id)
    return ArticleDetail(
        **_summary(row).model_dump(),
        doi=row["doi"],
        pmid=row["pmid"],
        abstract=row["abstract"],
        user_summary=row["user_summary"],
        metadata_conflicts=json.loads(row["metadata_conflicts_json"] or "[]"),
        assets=[_asset(asset) for asset in assets],
        annotations=annotations,
    )


@router.patch("/articles/{article_id}", response_model=ArticleDetail)
async def update_article(request: Request, article_id: int, value: ArticleUpdate) -> ArticleDetail:
    db = _state(request, "db")
    existing = db.fetch_one(
        "SELECT * FROM documents WHERE id = ? AND deleted_at IS NULL", (article_id,)
    )
    if not existing:
        raise HTTPException(404, "Article not found")
    updates = value.model_dump(exclude_unset=True)
    if not updates:
        return await get_article(request, article_id)
    if "reading_status" in updates and updates["reading_status"] not in {
        "unread",
        "reading",
        "read",
        "reference",
        "archived",
    }:
        raise HTTPException(422, "Invalid reading status")
    if "doi" in updates and updates["doi"] is not None:
        updates["doi"] = updates["doi"].strip().lower()
    if "title" in updates:
        updates["normalized_title"] = normalize_title(updates["title"] or "")
    bibliographic_fields = {
        "title",
        "authors",
        "journal",
        "publication_year",
        "doi",
        "pmid",
    }
    if bibliographic_fields & updates.keys():
        updates["metadata_status"] = "user"
    assignments = ", ".join(f"{key} = ?" for key in updates)
    db.execute(
        f"""
        UPDATE documents SET {assignments}, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        [*updates.values(), article_id],
    )
    return await get_article(request, article_id)


@router.post("/articles/{article_id}/review", response_model=ArticleDetail)
async def resolve_article_review(
    request: Request,
    article_id: int,
    value: ReviewResolution,
) -> ArticleDetail:
    db = _state(request, "db")
    row = db.fetch_one(
        """
        SELECT review_state, metadata_conflicts_json FROM documents
        WHERE id = ? AND deleted_at IS NULL
        """,
        (article_id,),
    )
    if not row:
        raise HTTPException(404, "Article not found")
    allowed_states = {"possible_duplicate", "metadata_conflict", "multi_article"}
    if row["review_state"] not in allowed_states:
        raise HTTPException(409, "This review state requires corrective processing")
    if row["review_state"] == "multi_article" and value.resolution != "keep_as_single_article":
        raise HTTPException(422, "Confirm whether the bundled PDF should remain one article")
    with db.transaction() as connection:
        connection.execute(
            """
            INSERT INTO review_decisions(
                document_id, prior_state, resolution, evidence_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                article_id,
                row["review_state"],
                value.resolution,
                row["metadata_conflicts_json"],
            ),
        )
        connection.execute(
            """
            UPDATE documents
            SET review_state = 'ready', metadata_conflicts_json = '[]',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (article_id,),
        )
    return await get_article(request, article_id)


@router.post("/articles/{article_id}/unlock", response_model=ImportJob, status_code=202)
async def unlock_article(
    request: Request,
    article_id: int,
    value: PasswordUnlockRequest,
) -> ImportJob:
    db = _state(request, "db")
    row = db.fetch_one(
        """
        SELECT id FROM documents
        WHERE id = ? AND deleted_at IS NULL AND review_state = 'password_required'
        """,
        (article_id,),
    )
    if not row:
        raise HTTPException(409, "This article is not waiting for a PDF password")
    jobs = _state(request, "jobs")
    job_id = jobs.create(
        "reindex",
        f"Encrypted article {article_id}",
        {"document_id": article_id},
        progress_total=1,
    )
    _state(request, "job_manager").enqueue(
        job_id,
        sensitive_input={"password": value.password.get_secret_value()},
    )
    result = jobs.get(job_id)
    assert result is not None
    return result


@router.post("/search", response_model=list[SearchHit])
async def search(request: Request, value: SearchQuery) -> list[SearchHit]:
    service = _state(request, "search")
    filters = SearchFilters(
        year_min=value.year_min,
        year_max=value.year_max,
        source_type=value.source_type,
        reading_status=value.reading_status,
        project_id=value.project_id,
        document_ids=value.document_ids,
    )
    results = service.search(value.text, filters=filters, limit=value.limit)
    return [
        SearchHit(
            rank=rank,
            article_id=result.document_id,
            asset_id=result.asset_id,
            title=result.title,
            authors=result.authors,
            journal=result.journal,
            publication_year=result.publication_year,
            source_type=result.source_type,
            page_number=result.page_number,
            passage_id=result.passage_id,
            snippet=result.snippet,
            bounding_boxes=result.bounding_boxes,
            match_reasons=[
                MatchReason(
                    code=reason.lower().replace(" ", "_"),
                    label=reason,
                )
                for reason in result.match_reasons
            ],
            why_saved=result.why_saved,
        )
        for rank, result in enumerate(results, start=1)
    ]


@router.post("/imports", response_model=ImportJob, status_code=202)
async def create_import(request: Request, value: ImportPathRequest) -> ImportJob:
    source = Path(value.path).expanduser().resolve()
    if value.source_kind == "folder" and not source.is_dir():
        raise HTTPException(422, "Selected folder does not exist")
    if value.source_kind == "file" and not source.is_file():
        raise HTTPException(422, "Selected file does not exist")
    if value.source_kind == "folder" and value.watch:
        _state(request, "db").execute(
            """
            INSERT INTO watched_folders(folder_path, recursive, enabled)
            VALUES (?, ?, 1)
            ON CONFLICT(folder_path) DO UPDATE SET
                recursive = excluded.recursive, enabled = 1
            """,
            (str(source), int(value.recursive)),
        )
    jobs = _state(request, "jobs")
    job_id = jobs.create(
        "import",
        source.name,
        {
            "path": str(source),
            "recursive": value.recursive,
            "project_id": value.project_id,
            "source_kind": value.source_kind,
        },
    )
    _state(request, "job_manager").enqueue(job_id)
    result = jobs.get(job_id)
    assert result is not None
    return result


@router.get("/watches/internal")
async def internal_watches(request: Request) -> list[dict[str, Any]]:
    """Rust-only response; the desktop command never forwards raw paths."""

    rows = _state(request, "db").fetch_all(
        """
        SELECT w.id, w.folder_path, w.recursive, (
            SELECT j.id
            FROM jobs j
            WHERE j.type = 'import'
              AND j.status IN ('queued', 'running', 'paused')
              AND json_extract(j.input_json, '$.source_kind') = 'folder'
              AND json_extract(j.input_json, '$.path') = w.folder_path
            ORDER BY j.created_at DESC
            LIMIT 1
        ) AS active_job_id
        FROM watched_folders w
        WHERE enabled = 1 ORDER BY id
        """
    )
    return [dict(row) for row in rows]


@router.post("/imports/zotero", response_model=ImportJob, status_code=202)
async def import_zotero(request: Request, value: ZoteroSyncRequest) -> ImportJob:
    jobs = _state(request, "jobs")
    job_id = jobs.create(
        "zotero_sync",
        "Zotero local library",
        {"base_url": value.base_url},
    )
    _state(request, "job_manager").enqueue(job_id)
    result = jobs.get(job_id)
    assert result is not None
    return result


@router.get("/jobs", response_model=list[ImportJob])
async def list_jobs(request: Request, limit: int = Query(100, ge=1, le=500)):
    return _state(request, "jobs").list_jobs(limit=limit)


@router.get("/jobs/{job_id}", response_model=ImportJob)
async def get_job(request: Request, job_id: str) -> ImportJob:
    result = _state(request, "jobs").get(job_id)
    if not result:
        raise HTTPException(404, "Job not found")
    return result


@router.get("/jobs/{job_id}/issues", response_model=list[ImportIssue])
async def list_job_issues(request: Request, job_id: str) -> list[ImportIssue]:
    if not _state(request, "jobs").get(job_id):
        raise HTTPException(404, "Job not found")
    return _state(request, "jobs").issues(job_id)


@router.post("/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(request: Request, job_id: str) -> dict[str, str]:
    if not _state(request, "jobs").get(job_id):
        raise HTTPException(404, "Job not found")
    _state(request, "jobs").request_cancel(job_id)
    return {"status": "cancel_requested"}


@router.post("/jobs/{job_id}/retry", response_model=ImportJob, status_code=202)
async def retry_job(request: Request, job_id: str) -> ImportJob:
    jobs = _state(request, "jobs")
    if not jobs.retry(job_id):
        raise HTTPException(409, "Job is not retryable")
    _state(request, "job_manager").enqueue(job_id)
    result = jobs.get(job_id)
    assert result is not None
    return result


@router.post(
    "/articles/{article_id}/annotations",
    response_model=Annotation,
    status_code=201,
)
async def create_annotation(
    request: Request, article_id: int, value: AnnotationCreate
) -> Annotation:
    try:
        return _state(request, "annotations").create(article_id, value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/articles/{article_id}/annotations", response_model=list[Annotation])
async def list_annotations(request: Request, article_id: int) -> list[Annotation]:
    return _state(request, "annotations").list_for_document(article_id)


@router.delete("/articles/{article_id}/annotations/{annotation_id}", status_code=204)
async def delete_annotation(request: Request, article_id: int, annotation_id: str) -> Response:
    if not _state(request, "annotations").delete(article_id, annotation_id):
        raise HTTPException(404, "Annotation not found")
    return Response(status_code=204)


@router.get("/articles/{article_id}/exports/annotations.md")
async def export_annotation_markdown(
    request: Request,
    article_id: int,
    asset_id: int | None = Query(default=None, ge=1),
) -> Response:
    db = _state(request, "db")
    row = db.fetch_one("SELECT title FROM documents WHERE id = ?", (article_id,))
    if not row:
        raise HTTPException(404, "Article not found")
    asset = _export_asset(db, article_id, asset_id)
    content = _state(request, "annotations").export_markdown(
        article_id,
        row["title"],
        file_id=int(asset["id"]),
    )
    return Response(
        content,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="article-{article_id}-annotations.md"'
        },
    )


@router.get("/articles/{article_id}/exports/annotations.xfdf")
async def export_annotation_xfdf(
    request: Request,
    article_id: int,
    asset_id: int | None = Query(default=None, ge=1),
) -> Response:
    db = _state(request, "db")
    row = _export_asset(db, article_id, asset_id)
    content = _state(request, "annotations").export_xfdf(
        article_id,
        row["file_name"],
        file_id=int(row["id"]),
    )
    return Response(
        content,
        media_type="application/vnd.adobe.xfdf",
        headers={"Content-Disposition": f'attachment; filename="article-{article_id}.xfdf"'},
    )


@router.get("/articles/{article_id}/exports/citation.ris")
async def export_article_ris(request: Request, article_id: int) -> Response:
    row = _state(request, "db").fetch_one(
        "SELECT * FROM documents WHERE id = ? AND deleted_at IS NULL",
        (article_id,),
    )
    if not row:
        raise HTTPException(404, "Article not found")
    return Response(
        documents_to_ris([dict(row)]),
        media_type="application/x-research-info-systems",
        headers={"Content-Disposition": f'attachment; filename="article-{article_id}.ris"'},
    )


@router.get("/articles/{article_id}/exports/citation.bib")
async def export_article_bibtex(request: Request, article_id: int) -> Response:
    row = _state(request, "db").fetch_one(
        "SELECT * FROM documents WHERE id = ? AND deleted_at IS NULL",
        (article_id,),
    )
    if not row:
        raise HTTPException(404, "Article not found")
    return Response(
        documents_to_bibtex([dict(row)]),
        media_type="application/x-bibtex",
        headers={"Content-Disposition": f'attachment; filename="article-{article_id}.bib"'},
    )


@router.get("/articles/{article_id}/exports/annotated.pdf")
async def export_annotated_pdf(
    request: Request,
    article_id: int,
    asset_id: int | None = Query(default=None, ge=1),
) -> FileResponse:
    db = _state(request, "db")
    row = _export_asset(db, article_id, asset_id)
    source = _state(request, "assets").resolve(
        row["object_path"] or row["file_path"], row["sha256"]
    )
    export_name = f"{safe_filename(Path(row['file_name']).stem)}-annotated.pdf"
    destination = _state(request, "settings").temp_dir / f"{uuid.uuid4().hex}-{export_name}"
    try:
        _state(request, "annotations").export_annotated_pdf(
            article_id,
            source,
            destination,
            file_id=int(row["id"]),
        )
    except Exception as exc:
        raise HTTPException(422, "The annotated PDF could not be generated") from exc
    return FileResponse(
        destination,
        filename=export_name,
        background=BackgroundTask(destination.unlink, missing_ok=True),
    )


@router.post("/assets/{asset_id}/access")
async def create_asset_access(request: Request, asset_id: int) -> dict[str, str]:
    db = _state(request, "db")
    row = db.fetch_one(
        """
        SELECT id FROM document_files
        WHERE id = ? AND availability = 'available'
        """,
        (asset_id,),
    )
    if not row:
        raise HTTPException(404, "Asset not found")
    token = secrets.token_urlsafe(32)
    # PDF.js makes lazy range requests while a paper is open. Keep the
    # read-only, asset-scoped capability alive for a normal work session; all
    # capabilities are revoked when the private core restarts.
    expires = datetime.now(UTC) + timedelta(hours=12)
    db.execute(
        "DELETE FROM asset_access_tokens WHERE expires_at <= ?",
        (datetime.now(UTC).isoformat(),),
    )
    db.execute(
        """
        INSERT INTO asset_access_tokens(token_hash, file_id, expires_at)
        VALUES (?, ?, ?)
        """,
        (hashlib.sha256(token.encode()).hexdigest(), asset_id, expires.isoformat()),
    )
    return {"url": f"/api/v1/assets/access/{token}", "expires_at": expires.isoformat()}


@router.get("/assets/access/{token}")
async def read_asset(request: Request, token: str) -> FileResponse:
    db = _state(request, "db")
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = db.fetch_one(
        """
        SELECT f.* FROM asset_access_tokens t
        JOIN document_files f ON f.id = t.file_id
        WHERE t.token_hash = ? AND t.expires_at > ?
        """,
        (digest, datetime.now(UTC).isoformat()),
    )
    if not row:
        raise HTTPException(404, "Asset access expired")
    origin = request.headers.get("origin")
    allowed_origins = {
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://127.0.0.1:1420",
    }
    if origin and origin not in allowed_origins:
        raise HTTPException(403, "Asset access is restricted to the desktop reader")
    path = _state(request, "assets").resolve(row["object_path"] or row["file_path"], row["sha256"])
    headers = {
        "Access-Control-Expose-Headers": "Accept-Ranges, Content-Length, Content-Range",
        "Cache-Control": "private, max-age=300",
        "X-Content-Type-Options": "nosniff",
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=row["file_name"],
        content_disposition_type="inline",
        headers=headers,
    )


@router.delete("/articles/{article_id}", status_code=204)
async def trash_article(request: Request, article_id: int) -> Response:
    if not _state(request, "library").move_to_trash(article_id):
        raise HTTPException(404, "Article not found")
    return Response(status_code=204)


@router.post("/trash/{article_id}/restore", status_code=204)
async def restore_article(request: Request, article_id: int) -> Response:
    if not _state(request, "library").restore(article_id):
        raise HTTPException(404, "Trashed article not found")
    return Response(status_code=204)


@router.get("/trash", response_model=list[TrashArticle])
async def list_trash(request: Request) -> list[TrashArticle]:
    return [
        TrashArticle(
            id=int(row["id"]),
            title=row["title"],
            deleted_at=row["deleted_at"],
            purge_after=row["purge_after"],
        )
        for row in _state(request, "library").list_trash()
    ]


@router.post("/backups")
async def create_backup(request: Request, value: BackupRequest) -> dict[str, str]:
    destination = Path(value.destination).expanduser().resolve()
    if destination.suffix.lower() != ".rmbak":
        destination = destination.with_suffix(".rmbak")
    try:
        async with _state(request, "backup_lock"):
            result = await asyncio.to_thread(
                _state(request, "backups").create,
                destination,
                value.passphrase,
            )
    except BackupError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(422, "The backup destination is unavailable") from exc
    return {"status": "created", "file_name": result.name}


@router.post("/backups/restore")
async def restore_backup(request: Request, value: RestoreRequest) -> dict[str, int]:
    manager = _state(request, "job_manager")
    try:
        async with _state(request, "backup_lock"):
            async with manager.maintenance():
                result = await asyncio.to_thread(
                    _state(request, "backups").restore,
                    Path(value.source),
                    value.passphrase,
                )
    except JobsBusy:
        raise HTTPException(
            409,
            "Wait for queued or running jobs before restoring a backup",
        ) from None
    except BackupError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(422, "The backup could not be read or restored") from exc
    _state(request, "search").invalidate()
    return result


@router.post("/models/install", status_code=202, response_model=ImportJob)
async def install_model(request: Request, value: ModelInstallRequest) -> ImportJob:
    if not value.consent_to_download:
        raise HTTPException(422, "Explicit model-download consent is required")
    if _state(request, "embedder").backend_name.startswith("fastembed:"):
        raise HTTPException(409, "The pinned offline model is already verified")
    jobs = _state(request, "jobs")
    job_id = jobs.create("install_model", "Offline Recall Search model", {})
    _state(request, "job_manager").enqueue(job_id)
    result = jobs.get(job_id)
    assert result is not None
    return result


@router.get("/projects")
async def list_projects(request: Request) -> list[dict[str, Any]]:
    rows = _state(request, "db").fetch_all(
        """
        SELECT p.*, COUNT(pd.document_id) AS article_count
        FROM projects p
        LEFT JOIN project_documents pd ON pd.project_id = p.id
        GROUP BY p.id
        ORDER BY p.updated_at DESC, p.name
        """
    )
    return [dict(row) for row in rows]


@router.post("/projects", status_code=201)
async def create_project(request: Request, value: ProjectCreate) -> dict[str, Any]:
    db = _state(request, "db")
    if not value.name.strip():
        raise HTTPException(422, "Project name cannot be blank")
    cursor = db.execute(
        """
        INSERT INTO projects(name, description, project_type)
        VALUES (?, ?, ?)
        """,
        (value.name.strip(), value.description.strip(), value.project_type),
    )
    row = db.fetch_one(
        "SELECT *, 0 AS article_count FROM projects WHERE id = ?",
        (cursor.lastrowid,),
    )
    assert row is not None
    return dict(row)


@router.get("/projects/{project_id}/articles", response_model=list[ArticleSummary])
async def list_project_articles(request: Request, project_id: int) -> list[ArticleSummary]:
    rows = _state(request, "db").fetch_all(
        """
        SELECT d.* FROM project_documents pd
        JOIN documents d ON d.id = pd.document_id
        WHERE pd.project_id = ? AND d.deleted_at IS NULL
        ORDER BY pd.added_at DESC
        """,
        (project_id,),
    )
    return [_summary(row) for row in rows]


@router.post(
    "/projects/{project_id}/articles/bulk",
    response_model=ProjectArticlesBulkResult,
)
async def add_project_articles(
    request: Request,
    project_id: int,
    value: ProjectArticlesBulkAdd,
) -> ProjectArticlesBulkResult:
    db = _state(request, "db")
    article_ids = list(dict.fromkeys(value.article_ids))
    with db.transaction() as connection:
        if not connection.execute(
            "SELECT id FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone():
            raise HTTPException(404, "Project not found")

        found_ids: set[int] = set()
        for offset in range(0, len(article_ids), 500):
            chunk = article_ids[offset : offset + 500]
            placeholders = ",".join("?" for _ in chunk)
            found_ids.update(
                int(row["id"])
                for row in connection.execute(
                    f"""
                    SELECT id FROM documents
                    WHERE deleted_at IS NULL AND id IN ({placeholders})
                    """,
                    chunk,
                ).fetchall()
            )
        missing = set(article_ids) - found_ids
        if missing:
            raise HTTPException(
                404,
                f"{len(missing)} selected article(s) were not found",
            )

        existing_ids = {
            int(row["document_id"])
            for row in connection.execute(
                "SELECT document_id FROM project_documents WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        }
        new_ids = [article_id for article_id in article_ids if article_id not in existing_ids]
        connection.executemany(
            """
            INSERT INTO project_documents(project_id, document_id, status)
            VALUES (?, ?, 'candidate')
            ON CONFLICT(project_id, document_id) DO NOTHING
            """,
            [(project_id, article_id) for article_id in new_ids],
        )
        if new_ids:
            connection.execute(
                "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (project_id,),
            )

    return ProjectArticlesBulkResult(
        project_id=project_id,
        requested=len(article_ids),
        added=len(new_ids),
        already_present=len(article_ids) - len(new_ids),
    )


@router.put("/projects/{project_id}/articles/{article_id}", status_code=204)
async def add_project_article(
    request: Request,
    project_id: int,
    article_id: int,
    value: ProjectArticleUpdate,
) -> Response:
    db = _state(request, "db")
    if not db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,)):
        raise HTTPException(404, "Project not found")
    if not db.fetch_one(
        "SELECT id FROM documents WHERE id = ? AND deleted_at IS NULL",
        (article_id,),
    ):
        raise HTTPException(404, "Article not found")
    db.execute(
        """
        INSERT INTO project_documents(project_id, document_id, status)
        VALUES (?, ?, ?)
        ON CONFLICT(project_id, document_id) DO UPDATE SET status = excluded.status
        """,
        (project_id, article_id, value.status),
    )
    return Response(status_code=204)


@router.delete("/projects/{project_id}/articles/{article_id}", status_code=204)
async def remove_project_article(request: Request, project_id: int, article_id: int) -> Response:
    _state(request, "db").execute(
        "DELETE FROM project_documents WHERE project_id = ? AND document_id = ?",
        (project_id, article_id),
    )
    return Response(status_code=204)


@router.patch("/settings/privacy")
async def update_privacy_settings(
    request: Request, value: PrivacySettingsUpdate
) -> dict[str, bool]:
    settings = _state(request, "settings")
    db = _state(request, "db")
    for key, setting_value in value.model_dump(exclude_unset=True).items():
        setattr(settings, key, bool(setting_value))
        db.execute(
            """
            INSERT INTO app_settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, "true" if setting_value else "false"),
        )
    return {
        "enable_network_metadata": settings.enable_network_metadata,
        "diagnostics_enabled": settings.diagnostics_enabled,
    }


@router.post("/support-bundles")
async def create_support_bundle(request: Request, value: SupportBundleRequest) -> dict[str, str]:
    destination = Path(value.destination).expanduser().resolve()
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    try:
        result = _state(request, "support").create(destination)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(422, "The support bundle destination is unavailable") from exc
    return {"status": "created", "file_name": result.name}
