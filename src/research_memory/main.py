from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import secrets
import signal
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from research_memory.api import router as production_api
from research_memory.config import Settings, get_settings
from research_memory.db import Database
from research_memory.services.annotations import AnnotationService
from research_memory.services.assets import AssetStore
from research_memory.services.backup import BackupService
from research_memory.services.embeddings import create_embedder, install_fastembed_model
from research_memory.services.export import (
    documents_to_bibtex,
    documents_to_ris,
    project_to_markdown,
)
from research_memory.services.ingest import IngestionService
from research_memory.services.jobs import BackgroundJobManager, JobContext, JobStore
from research_memory.services.library import LibraryService
from research_memory.services.personalized_taxonomy import PersonalizedTaxonomyBuilder
from research_memory.services.research_profile import ResearchProfileService
from research_memory.services.search import SearchFilters, SearchService
from research_memory.services.support import SupportBundleService
from research_memory.services.taxonomy_assignments import TaxonomyAssignmentService
from research_memory.services.taxonomy_catalog import TaxonomyCatalog
from research_memory.services.zotero import ZoteroImporter
from research_memory.utils import normalize_title, safe_filename, truncate

PACKAGE_DIR = Path(__file__).resolve().parent
SOURCE_TYPES = [
    "journal_article",
    "randomized_trial",
    "prospective_cohort",
    "retrospective_study",
    "systematic_review",
    "guideline",
    "review",
    "case_report",
]
READING_STATUSES = ["unread", "reading", "read", "reference", "archived"]
PROJECT_TYPES = [
    "collection",
    "manuscript",
    "systematic_review",
    "guideline",
    "lecture",
    "curriculum",
    "grant",
    "journal_club",
]
PROJECT_STATUSES = [
    "candidate",
    "to_review",
    "included",
    "excluded",
    "background",
    "data_extracted",
    "ready_for_synthesis",
]


def _redirect(path: str, message: str | None = None, *, error: bool = False) -> RedirectResponse:
    if message:
        separator = "&" if "?" in path else "?"
        key = "error" if error else "notice"
        path = f"{path}{separator}{key}={quote(message)}"
    return RedirectResponse(path, status_code=303)


def _parse_int(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    desktop_parent_pid = os.getppid() if settings.ipc_token else None
    # The sidecar needs the session token once at startup, but OCR/model child
    # processes must not inherit it.
    if settings.ipc_token:
        os.environ.pop("RESEARCH_MEMORY_IPC_TOKEN", None)
    settings.ensure_directories()
    db = Database(settings.database_path, settings.backups_dir)
    db.initialize()
    taxonomy_catalog = TaxonomyCatalog.load()
    taxonomy_catalog.install(db)
    research_profile = ResearchProfileService(db, taxonomy_catalog)
    personalized_taxonomy = PersonalizedTaxonomyBuilder(taxonomy_catalog)
    taxonomy_assignments = TaxonomyAssignmentService(db, taxonomy_catalog)
    # Reader capabilities are scoped to one desktop-core session. A stale URL
    # copied from a prior process must never become valid after restart.
    db.execute("DELETE FROM asset_access_tokens")
    for key in ("enable_network_metadata", "diagnostics_enabled"):
        persisted = db.scalar("SELECT value FROM app_settings WHERE key = ?", (key,))
        if persisted is not None:
            setattr(settings, key, str(persisted).lower() == "true")
    embedder = create_embedder(
        settings.embedding_backend,
        settings.embedding_model,
        settings.resolved_model_dir,
    )
    assets = AssetStore(settings)
    ingestion = IngestionService(db, settings, embedder, assets)
    search = SearchService(db, embedder, settings.data_dir / "indexes")
    annotations = AnnotationService(db)
    backups = BackupService(db, settings)
    support = SupportBundleService(db, settings)
    library_service = LibraryService(db, assets)
    jobs = JobStore(db)
    job_manager = BackgroundJobManager(jobs, settings.worker_count)
    backup_lock = asyncio.Lock()
    zotero = ZoteroImporter(db, ingestion)
    job_manager.register("import", ingestion.handle_import_job)
    job_manager.register("reindex", ingestion.handle_reindex_job)
    job_manager.register("zotero_sync", zotero.handle_job)

    def enqueue_reindex(document_id: int) -> bool:
        existing = db.fetch_one(
            """
            SELECT id FROM jobs
            WHERE type = 'reindex'
              AND json_extract(input_json, '$.document_id') = ?
              AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (document_id,),
        )
        if existing:
            job_manager.enqueue(str(existing["id"]))
            return False
        reindex_id = jobs.create(
            "reindex",
            f"Article {document_id}",
            {"document_id": document_id},
            progress_total=1,
        )
        job_manager.enqueue(reindex_id)
        return True

    async def migrate_assets_handler(
        context: JobContext, _payload: dict[str, object]
    ) -> dict[str, int]:
        context.update("copying_legacy_assets", current=0, total=1)
        migrated = await asyncio.to_thread(ingestion.migrate_legacy_assets)
        queued = 0
        for row in db.fetch_all(
            """
            SELECT DISTINCT d.id
            FROM documents d
            JOIN document_files f ON f.document_id = d.id
            WHERE d.deleted_at IS NULL
              AND d.extraction_status = 'reindex_required'
              AND f.availability = 'available'
            ORDER BY d.id
            """
        ):
            queued += int(enqueue_reindex(int(row["id"])))
        context.update("complete", current=1, total=1)
        return {"migrated": migrated, "reindex_jobs_queued": queued}

    job_manager.register("migrate_assets", migrate_assets_handler, exclusive=True)

    async def install_model_handler(
        context: JobContext, _payload: dict[str, object]
    ) -> dict[str, object]:
        nonlocal embedder, search
        context.update("downloading_model", current=0, total=2)
        installed = await asyncio.to_thread(
            install_fastembed_model,
            settings.embedding_model,
            settings.resolved_model_dir,
        )
        context.update("verifying_model", current=1, total=2)
        embedder = installed
        ingestion.embedder = installed
        search = SearchService(db, installed, settings.data_dir / "indexes")
        app.state.embedder = installed
        app.state.search = search
        db.execute(
            """
            INSERT INTO app_settings(key, value) VALUES ('embedding_backend', 'fastembed')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
        queued = 0
        for row in db.fetch_all("SELECT id FROM documents WHERE deleted_at IS NULL ORDER BY id"):
            queued += int(enqueue_reindex(int(row["id"])))
        context.update("complete", current=2, total=2)
        return {"backend": installed.backend_name, "reindex_jobs_queued": queued}

    job_manager.register("install_model", install_model_handler, exclusive=True)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        async def stop_if_desktop_parent_exits(parent_pid: int) -> None:
            while True:
                await asyncio.sleep(1)
                if os.getppid() != parent_pid:
                    os.kill(os.getpid(), signal.SIGTERM)
                    return

        parent_monitor = (
            asyncio.create_task(stop_if_desktop_parent_exits(desktop_parent_pid))
            if desktop_parent_pid is not None
            else None
        )
        jobs.reconcile_duplicate_import_failures()
        await job_manager.start()
        legacy_count = int(
            db.scalar(
                """
                SELECT COUNT(*) FROM document_files
                WHERE object_path = '' OR source_kind = 'legacy'
                """
            )
            or 0
        )
        migration_active = int(
            db.scalar(
                """
                SELECT COUNT(*) FROM jobs
                WHERE type = 'migrate_assets'
                  AND status IN ('queued', 'running', 'paused')
                """
            )
            or 0
        )
        if legacy_count and not migration_active:
            migration_id = jobs.create(
                "migrate_assets",
                "v0.1 managed files",
                {},
                progress_total=1,
            )
            job_manager.enqueue(migration_id)
        await asyncio.to_thread(library_service.purge_expired)
        try:
            yield
        finally:
            if parent_monitor is not None:
                parent_monitor.cancel()
                with suppress(asyncio.CancelledError):
                    await parent_monitor
            await job_manager.stop()

    app = FastAPI(
        title="Research Memory",
        version="0.2.0",
        description="A private, local-first literature index and research workspace.",
        lifespan=lifespan,
        docs_url="/docs" if settings.allow_legacy_web else None,
        redoc_url="/redoc" if settings.allow_legacy_web else None,
        openapi_url="/openapi.json" if settings.allow_legacy_web else None,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )
    app.state.settings = settings
    app.state.db = db
    app.state.embedder = embedder
    app.state.ingestion = ingestion
    app.state.search = search
    app.state.assets = assets
    app.state.annotations = annotations
    app.state.backups = backups
    app.state.support = support
    app.state.library = library_service
    app.state.jobs = jobs
    app.state.job_manager = job_manager
    app.state.backup_lock = backup_lock
    app.state.zotero = zotero
    app.state.taxonomy_catalog = taxonomy_catalog
    app.state.research_profile = research_profile
    app.state.personalized_taxonomy = personalized_taxonomy
    app.state.taxonomy_assignments = taxonomy_assignments

    @app.middleware("http")
    async def private_ipc_boundary(request: Request, call_next):
        path = request.url.path
        opaque_asset_access = path.startswith("/api/v1/assets/access/")
        response: Response
        client_host = request.client.host if request.client else ""
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            response = JSONResponse(
                {"detail": "Research Memory accepts loopback clients only"},
                status_code=403,
            )
        elif (
            path.startswith("/api/v1")
            and not opaque_asset_access
            and settings.ipc_token
            and not secrets.compare_digest(
                request.headers.get("X-Research-Memory-Token", ""),
                settings.ipc_token,
            )
        ):
            response = JSONResponse(
                {"detail": "Invalid desktop IPC session"},
                status_code=401,
            )
        elif job_manager.in_maintenance:
            response = JSONResponse(
                {"detail": "The library is temporarily unavailable during restore"},
                status_code=503,
                headers={"Retry-After": "2"},
            )
        elif not settings.allow_legacy_web and not path.startswith("/api/v1") and path != "/health":
            response = JSONResponse({"detail": "Desktop API only"}, status_code=404)
        else:
            response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        return response

    app.include_router(production_api)

    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    templates.env.filters["truncate_text"] = truncate
    templates.env.filters["fromjson"] = lambda value: json.loads(value or "{}")
    templates.env.globals.update(
        source_types=SOURCE_TYPES,
        reading_statuses=READING_STATUSES,
        project_types=PROJECT_TYPES,
        project_statuses=PROJECT_STATUSES,
    )
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    def context(request: Request, **kwargs):
        return {
            "request": request,
            "notice": request.query_params.get("notice"),
            "error": request.query_params.get("error"),
            "embedding_backend": embedder.backend_name,
            "embedding_warning": embedder.warning,
            **kwargs,
        }

    def render_template(name: str, template_context: dict):
        return templates.TemplateResponse(
            request=template_context["request"], name=name, context=template_context
        )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        counts = {
            "documents": db.scalar("SELECT COUNT(*) FROM documents") or 0,
            "unread": db.scalar("SELECT COUNT(*) FROM documents WHERE reading_status = 'unread'")
            or 0,
            "projects": db.scalar("SELECT COUNT(*) FROM projects") or 0,
            "needs_ocr": db.scalar(
                "SELECT COUNT(*) FROM documents WHERE extraction_status = 'needs_ocr'"
            )
            or 0,
        }
        recent = db.fetch_all(
            """
            SELECT d.*, (SELECT file_name FROM document_files f
                         WHERE f.document_id = d.id ORDER BY is_primary DESC, id LIMIT 1) AS file_name
            FROM documents d ORDER BY d.created_at DESC LIMIT 8
            """
        )
        projects = db.fetch_all(
            """
            SELECT p.*, COUNT(pd.document_id) AS paper_count
            FROM projects p LEFT JOIN project_documents pd ON pd.project_id = p.id
            GROUP BY p.id ORDER BY p.updated_at DESC LIMIT 6
            """
        )
        watched = db.fetch_all("SELECT * FROM watched_folders WHERE enabled = 1 ORDER BY id")
        return render_template(
            "dashboard.html",
            context(
                request,
                counts=counts,
                recent=recent,
                projects=projects,
                watched=watched,
            ),
        )

    @app.get("/import", response_class=HTMLResponse)
    async def import_page(request: Request):
        projects = db.fetch_all("SELECT id, name FROM projects ORDER BY name")
        watched = db.fetch_all("SELECT * FROM watched_folders ORDER BY id DESC")
        return render_template(
            "import.html", context(request, projects=projects, watched=watched, results=None)
        )

    @app.post("/import/files", response_class=HTMLResponse)
    async def import_files(
        request: Request,
        files: list[UploadFile] = File(...),
        project_id: str = Form(""),
    ):
        results = []
        parsed_project_id = _parse_int(project_id)
        for upload in files:
            if not upload.filename:
                continue
            temp_path = settings.import_dir / safe_filename(upload.filename)
            counter = 1
            while temp_path.exists():
                temp_path = settings.import_dir / (f"{temp_path.stem}-{counter}{temp_path.suffix}")
                counter += 1
            size = 0
            try:
                with temp_path.open("wb") as handle:
                    while chunk := await upload.read(1024 * 1024):
                        size += len(chunk)
                        if size > settings.max_upload_mb * 1024 * 1024:
                            raise ValueError(
                                f"{upload.filename} exceeds the {settings.max_upload_mb} MB limit."
                            )
                        handle.write(chunk)
                result = await ingestion.ingest_path(
                    temp_path,
                    copy_into_library=True,
                    project_id=parsed_project_id,
                )
                results.append(result)
            except Exception as exc:
                from research_memory.services.ingest import IngestResult

                results.append(IngestResult("error", None, upload.filename, str(exc)))
            finally:
                temp_path.unlink(missing_ok=True)
        search.invalidate()
        projects = db.fetch_all("SELECT id, name FROM projects ORDER BY name")
        watched = db.fetch_all("SELECT * FROM watched_folders ORDER BY id DESC")
        return render_template(
            "import.html", context(request, projects=projects, watched=watched, results=results)
        )

    @app.post("/import/folder")
    async def import_folder(
        folder_path: str = Form(...),
        recursive: bool = Form(False),
        copy_into_library: bool = Form(False),
        register_watch: bool = Form(False),
        project_id: str = Form(""),
    ):
        folder = Path(folder_path).expanduser()
        if not folder.exists() or not folder.is_dir():
            return _redirect("/import", "The selected folder does not exist.", error=True)
        if register_watch:
            db.execute(
                """
                INSERT INTO watched_folders(folder_path, recursive, enabled)
                VALUES (?, ?, 1)
                ON CONFLICT(folder_path) DO UPDATE SET recursive = excluded.recursive, enabled = 1
                """,
                (str(folder.resolve()), int(recursive)),
            )
        results = await ingestion.ingest_folder(
            folder,
            recursive=recursive,
            copy_into_library=copy_into_library,
            project_id=_parse_int(project_id),
        )
        search.invalidate()
        counts: dict[str, int] = {}
        for result in results:
            counts[result.status] = counts.get(result.status, 0) + 1
        summary = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
        return _redirect("/import", summary or "No PDF files were found.")

    @app.post("/watch/{watch_id}/scan")
    async def scan_watch(watch_id: int):
        watch = db.fetch_one("SELECT * FROM watched_folders WHERE id = ?", (watch_id,))
        if not watch:
            raise HTTPException(404, "Watched folder not found")
        results = await ingestion.ingest_folder(
            watch["folder_path"], recursive=bool(watch["recursive"]), copy_into_library=False
        )
        db.execute(
            "UPDATE watched_folders SET last_scanned_at = CURRENT_TIMESTAMP WHERE id = ?",
            (watch_id,),
        )
        search.invalidate()
        indexed = sum(1 for result in results if result.status == "indexed")
        return _redirect("/", f"Folder scan completed: {indexed} new papers indexed.")

    @app.post("/watch/{watch_id}/delete")
    async def delete_watch(watch_id: int):
        db.execute("DELETE FROM watched_folders WHERE id = ?", (watch_id,))
        return _redirect("/import", "Watched folder removed. Indexed papers were preserved.")

    @app.get("/library", response_class=HTMLResponse)
    async def library(
        request: Request,
        q: str = "",
        reading_status: str = "",
        source_type: str = "",
        year_min: str = "",
        year_max: str = "",
        sort: str = "recent",
        page: int = Query(1, ge=1),
    ):
        page_size = 40
        clauses = ["1 = 1"]
        parameters: list[object] = []
        if q:
            pattern = f"%{q.lower()}%"
            clauses.append(
                "(lower(title) LIKE ? OR lower(authors) LIKE ? OR lower(abstract) LIKE ? OR lower(why_saved) LIKE ?)"
            )
            parameters.extend([pattern] * 4)
        if reading_status:
            clauses.append("reading_status = ?")
            parameters.append(reading_status)
        if source_type:
            clauses.append("source_type = ?")
            parameters.append(source_type)
        if _parse_int(year_min):
            clauses.append("publication_year >= ?")
            parameters.append(_parse_int(year_min))
        if _parse_int(year_max):
            clauses.append("publication_year <= ?")
            parameters.append(_parse_int(year_max))
        order_by = {
            "recent": "created_at DESC",
            "year_desc": "publication_year DESC, title",
            "year_asc": "publication_year ASC, title",
            "title": "title COLLATE NOCASE",
            "importance": "importance DESC, created_at DESC",
        }.get(sort, "created_at DESC")
        where = " AND ".join(clauses)
        total = db.scalar(f"SELECT COUNT(*) FROM documents WHERE {where}", parameters) or 0
        rows = db.fetch_all(
            f"""
            SELECT d.*, (SELECT COUNT(*) FROM document_files f WHERE f.document_id = d.id) AS file_count
            FROM documents d WHERE {where}
            ORDER BY {order_by} LIMIT ? OFFSET ?
            """,
            parameters + [page_size, (page - 1) * page_size],
        )
        return render_template(
            "library.html",
            context(
                request,
                documents=rows,
                total=total,
                page=page,
                page_size=page_size,
                q=q,
                selected_status=reading_status,
                selected_source_type=source_type,
                year_min=year_min,
                year_max=year_max,
                sort=sort,
            ),
        )

    @app.get("/search", response_class=HTMLResponse)
    async def search_page(
        request: Request,
        q: str = "",
        source_type: str = "",
        reading_status: str = "",
        year_min: str = "",
        year_max: str = "",
        project_id: str = "",
    ):
        filters = SearchFilters(
            source_type=source_type or None,
            reading_status=reading_status or None,
            year_min=_parse_int(year_min),
            year_max=_parse_int(year_max),
            project_id=_parse_int(project_id),
        )
        results = search.search(q, filters=filters, limit=40) if q.strip() else []
        projects = db.fetch_all("SELECT id, name FROM projects ORDER BY name")
        return render_template(
            "search.html",
            context(
                request,
                q=q,
                results=results,
                projects=projects,
                selected_source_type=source_type,
                selected_status=reading_status,
                year_min=year_min,
                year_max=year_max,
                selected_project_id=_parse_int(project_id),
            ),
        )

    @app.post("/search/save")
    async def save_search(name: str = Form(...), query: str = Form(...)):
        db.execute("INSERT INTO saved_searches(name, query) VALUES (?, ?)", (name, query))
        return _redirect(f"/search?q={quote(query)}", "Search saved.")

    @app.get("/documents/{document_id}", response_class=HTMLResponse)
    async def document_detail(request: Request, document_id: int, page: int | None = None):
        document = db.fetch_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        if not document:
            raise HTTPException(404, "Document not found")
        files = db.fetch_all(
            "SELECT * FROM document_files WHERE document_id = ? ORDER BY is_primary DESC, id",
            (document_id,),
        )
        notes = db.fetch_all(
            "SELECT * FROM notes WHERE document_id = ? ORDER BY created_at DESC", (document_id,)
        )
        projects = db.fetch_all(
            """
            SELECT p.*, pd.status, pd.exclusion_reason,
                   CASE WHEN pd.document_id IS NULL THEN 0 ELSE 1 END AS attached
            FROM projects p LEFT JOIN project_documents pd
              ON pd.project_id = p.id AND pd.document_id = ?
            ORDER BY p.name
            """,
            (document_id,),
        )
        related = search.search(document["title"], limit=6)
        related = [item for item in related if item.document_id != document_id][:5]
        return render_template(
            "document.html",
            context(
                request,
                document=document,
                files=files,
                notes=notes,
                projects=projects,
                related=related,
                initial_page=page or 1,
            ),
        )

    @app.get("/documents/{document_id}/pdf")
    async def document_pdf(document_id: int, file_id: int | None = None):
        if file_id:
            file_row = db.fetch_one(
                "SELECT * FROM document_files WHERE id = ? AND document_id = ?",
                (file_id, document_id),
            )
        else:
            file_row = db.fetch_one(
                """
                SELECT * FROM document_files WHERE document_id = ?
                ORDER BY is_primary DESC, id LIMIT 1
                """,
                (document_id,),
            )
        if not file_row:
            raise HTTPException(404, "PDF file record not found")
        path = Path(file_row["file_path"])
        if not path.exists():
            raise HTTPException(404, "The indexed PDF has moved or is unavailable")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=file_row["file_name"],
            content_disposition_type="inline",
        )

    @app.post("/documents/{document_id}/update")
    async def update_document(
        document_id: int,
        title: str = Form(...),
        authors: str = Form(""),
        journal: str = Form(""),
        publication_year: str = Form(""),
        doi: str = Form(""),
        pmid: str = Form(""),
        reading_status: str = Form("unread"),
        importance: int = Form(0),
        why_saved: str = Form(""),
        user_summary: str = Form(""),
    ):
        db.execute(
            """
            UPDATE documents SET title = ?, normalized_title = ?, authors = ?, journal = ?, publication_year = ?,
                doi = ?, pmid = ?, reading_status = ?, importance = ?, why_saved = ?,
                user_summary = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                title.strip(),
                normalize_title(title),
                authors.strip(),
                journal.strip(),
                _parse_int(publication_year),
                doi.strip().lower(),
                pmid.strip(),
                reading_status if reading_status in READING_STATUSES else "unread",
                max(0, min(5, importance)),
                why_saved.strip(),
                user_summary.strip(),
                document_id,
            ),
        )
        return _redirect(f"/documents/{document_id}", "Article details saved.")

    @app.post("/documents/{document_id}/notes")
    async def add_note(
        document_id: int,
        body: str = Form(...),
        note_type: str = Form("note"),
        page_number: str = Form(""),
    ):
        if body.strip():
            db.execute(
                "INSERT INTO notes(document_id, note_type, body, page_number) VALUES (?, ?, ?, ?)",
                (document_id, note_type, body.strip(), _parse_int(page_number)),
            )
        return _redirect(f"/documents/{document_id}", "Note added.")

    @app.post("/documents/{document_id}/notes/{note_id}/delete")
    async def delete_note(document_id: int, note_id: int):
        db.execute("DELETE FROM notes WHERE id = ? AND document_id = ?", (note_id, document_id))
        return _redirect(f"/documents/{document_id}", "Note deleted.")

    @app.post("/documents/{document_id}/projects")
    async def attach_project(
        document_id: int,
        project_id: int = Form(...),
        status: str = Form("candidate"),
    ):
        db.execute(
            """
            INSERT INTO project_documents(project_id, document_id, status)
            VALUES (?, ?, ?)
            ON CONFLICT(project_id, document_id) DO UPDATE SET status = excluded.status
            """,
            (
                project_id,
                document_id,
                status if status in PROJECT_STATUSES else "candidate",
            ),
        )
        return _redirect(f"/documents/{document_id}", "Project membership updated.")

    @app.get("/projects", response_class=HTMLResponse)
    async def projects_page(request: Request):
        rows = db.fetch_all(
            """
            SELECT p.*, COUNT(pd.document_id) AS paper_count,
                   SUM(CASE WHEN pd.status = 'included' THEN 1 ELSE 0 END) AS included_count
            FROM projects p LEFT JOIN project_documents pd ON pd.project_id = p.id
            GROUP BY p.id ORDER BY p.updated_at DESC
            """
        )
        return render_template("projects.html", context(request, projects=rows))

    @app.post("/projects")
    async def create_project(
        name: str = Form(...),
        description: str = Form(""),
        project_type: str = Form("collection"),
        central_question: str = Form(""),
    ):
        cursor = db.execute(
            """
            INSERT INTO projects(name, description, project_type, central_question)
            VALUES (?, ?, ?, ?)
            """,
            (
                name.strip(),
                description.strip(),
                project_type if project_type in PROJECT_TYPES else "collection",
                central_question.strip(),
            ),
        )
        return _redirect(f"/projects/{cursor.lastrowid}", "Project created.")

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    async def project_detail(request: Request, project_id: int):
        project = db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project:
            raise HTTPException(404, "Project not found")
        papers = db.fetch_all(
            """
            SELECT d.*, pd.status AS project_status, pd.exclusion_reason, pd.added_at
            FROM project_documents pd JOIN documents d ON d.id = pd.document_id
            WHERE pd.project_id = ?
            ORDER BY CASE pd.status
                WHEN 'included' THEN 1 WHEN 'data_extracted' THEN 2
                WHEN 'ready_for_synthesis' THEN 3 WHEN 'to_review' THEN 4
                WHEN 'candidate' THEN 5 WHEN 'background' THEN 6 ELSE 7 END,
                d.publication_year DESC, d.title
            """,
            (project_id,),
        )
        status_counts = db.fetch_all(
            """
            SELECT status, COUNT(*) AS count_value FROM project_documents
            WHERE project_id = ? GROUP BY status ORDER BY status
            """,
            (project_id,),
        )
        return render_template(
            "project.html",
            context(request, project=project, papers=papers, status_counts=status_counts),
        )

    @app.post("/projects/{project_id}/update")
    async def update_project(
        project_id: int,
        name: str = Form(...),
        description: str = Form(""),
        central_question: str = Form(""),
        project_type: str = Form("collection"),
    ):
        db.execute(
            """
            UPDATE projects SET name = ?, description = ?, central_question = ?,
                project_type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (name, description, central_question, project_type, project_id),
        )
        return _redirect(f"/projects/{project_id}", "Project updated.")

    @app.post("/projects/{project_id}/documents/{document_id}/update")
    async def update_project_document(
        project_id: int,
        document_id: int,
        status: str = Form("candidate"),
        exclusion_reason: str = Form(""),
    ):
        db.execute(
            """
            UPDATE project_documents SET status = ?, exclusion_reason = ?
            WHERE project_id = ? AND document_id = ?
            """,
            (
                status if status in PROJECT_STATUSES else "candidate",
                exclusion_reason.strip(),
                project_id,
                document_id,
            ),
        )
        return _redirect(f"/projects/{project_id}", "Paper status updated.")

    @app.post("/projects/{project_id}/documents/{document_id}/remove")
    async def remove_project_document(project_id: int, document_id: int):
        db.execute(
            "DELETE FROM project_documents WHERE project_id = ? AND document_id = ?",
            (project_id, document_id),
        )
        return _redirect(f"/projects/{project_id}", "Paper removed from project.")

    @app.get("/documents/{document_id}/export.bib")
    async def export_document_bibtex(document_id: int):
        row = db.fetch_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        if not row:
            raise HTTPException(404, "Document not found")
        return Response(
            documents_to_bibtex([dict(row)]),
            media_type="application/x-bibtex",
            headers={"Content-Disposition": f'attachment; filename="paper-{document_id}.bib"'},
        )

    @app.get("/documents/{document_id}/export.ris")
    async def export_document_ris(document_id: int):
        row = db.fetch_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        if not row:
            raise HTTPException(404, "Document not found")
        return Response(
            documents_to_ris([dict(row)]),
            media_type="application/x-research-info-systems",
            headers={"Content-Disposition": f'attachment; filename="paper-{document_id}.ris"'},
        )

    @app.get("/projects/{project_id}/export.csv")
    async def export_project_csv(project_id: int):
        project = db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project:
            raise HTTPException(404, "Project not found")
        rows = db.fetch_all(
            """
            SELECT d.title, d.authors, d.journal, d.publication_year, d.doi, d.pmid,
                   d.source_type, pd.status, pd.exclusion_reason, d.why_saved, d.user_summary
            FROM project_documents pd JOIN documents d ON d.id = pd.document_id
            WHERE pd.project_id = ? ORDER BY d.publication_year DESC, d.title
            """,
            (project_id,),
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "title",
                "authors",
                "journal",
                "year",
                "doi",
                "pmid",
                "source_type",
                "project_status",
                "exclusion_reason",
                "why_saved",
                "user_summary",
            ]
        )
        for row in rows:
            writer.writerow(list(row))
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="project-{project_id}-evidence.csv"'
            },
        )

    @app.get("/projects/{project_id}/export.md")
    async def export_project_markdown(project_id: int):
        project = db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project:
            raise HTTPException(404, "Project not found")
        rows = db.fetch_all(
            """
            SELECT d.*, pd.status AS project_status, pd.exclusion_reason
            FROM project_documents pd JOIN documents d ON d.id = pd.document_id
            WHERE pd.project_id = ? ORDER BY d.publication_year DESC, d.title
            """,
            (project_id,),
        )
        return Response(
            project_to_markdown(dict(project), [dict(row) for row in rows]),
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="project-{project_id}-evidence.md"'
            },
        )

    @app.get("/projects/{project_id}/export.bib")
    async def export_project_bibtex(project_id: int):
        rows = db.fetch_all(
            """SELECT d.* FROM project_documents pd JOIN documents d ON d.id = pd.document_id
               WHERE pd.project_id = ? ORDER BY d.publication_year DESC, d.title""",
            (project_id,),
        )
        return Response(
            documents_to_bibtex([dict(row) for row in rows]),
            media_type="application/x-bibtex",
            headers={"Content-Disposition": f'attachment; filename="project-{project_id}.bib"'},
        )

    @app.get("/projects/{project_id}/export.ris")
    async def export_project_ris(project_id: int):
        rows = db.fetch_all(
            """SELECT d.* FROM project_documents pd JOIN documents d ON d.id = pd.document_id
               WHERE pd.project_id = ? ORDER BY d.publication_year DESC, d.title""",
            (project_id,),
        )
        return Response(
            documents_to_ris([dict(row) for row in rows]),
            media_type="application/x-research-info-systems",
            headers={"Content-Disposition": f'attachment; filename="project-{project_id}.ris"'},
        )

    @app.get("/api/search")
    async def api_search(q: str, limit: int = Query(10, ge=1, le=50)):
        results = search.search(q, limit=limit)
        return JSONResponse(
            [
                {
                    "document_id": result.document_id,
                    "title": result.title,
                    "year": result.publication_year,
                    "page": result.page_number,
                    "snippet": result.snippet,
                    "score": round(result.score, 4),
                    "relevance": result.relevance,
                    "match_reasons": result.match_reasons,
                }
                for result in results
            ]
        )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "documents": db.scalar("SELECT COUNT(*) FROM documents") or 0,
            "embedding_backend": embedder.backend_name,
        }

    return app


app = create_app()
