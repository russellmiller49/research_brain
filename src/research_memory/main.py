from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from research_memory.config import Settings, get_settings
from research_memory.db import Database
from research_memory.services.embeddings import create_embedder
from research_memory.services.ingest import IngestionService
from research_memory.services.export import documents_to_bibtex, documents_to_ris, project_to_markdown
from research_memory.services.qna import QuestionAnsweringService
from research_memory.services.search import SearchFilters, SearchService
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
        return int(value)
    except (TypeError, ValueError):
        return None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_directories()
    db = Database(settings.database_path)
    db.initialize()
    embedder = create_embedder(settings.embedding_backend, settings.embedding_model)
    ingestion = IngestionService(db, settings, embedder)
    search = SearchService(db, embedder)
    qna = QuestionAnsweringService(db, search, settings)

    app = FastAPI(
        title="Research Memory",
        version="0.1.0",
        description="A private, local-first literature index and research workspace.",
    )
    app.state.settings = settings
    app.state.db = db
    app.state.embedder = embedder
    app.state.ingestion = ingestion
    app.state.search = search
    app.state.qna = qna

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
        topic_counts: dict[str, int] = {}
        for row in db.fetch_all("SELECT keywords_json FROM documents"):
            try:
                keywords = json.loads(row["keywords_json"] or "[]")
            except json.JSONDecodeError:
                keywords = []
            for keyword in keywords[:8]:
                topic_counts[keyword] = topic_counts.get(keyword, 0) + 1
        topics = sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
        watched = db.fetch_all("SELECT * FROM watched_folders WHERE enabled = 1 ORDER BY id")
        return render_template(
            "dashboard.html",
            context(
                request,
                counts=counts,
                recent=recent,
                projects=projects,
                topics=topics,
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
                temp_path = settings.import_dir / (
                    f"{temp_path.stem}-{counter}{temp_path.suffix}"
                )
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
        try:
            study_card = json.loads(document["study_card_json"] or "{}")
        except json.JSONDecodeError:
            study_card = {}
        try:
            keywords = json.loads(document["keywords_json"] or "[]")
        except json.JSONDecodeError:
            keywords = []
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
                study_card=study_card,
                keywords=keywords,
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
            documents_to_bibtex([row]),
            media_type="application/x-bibtex",
            headers={"Content-Disposition": f'attachment; filename="paper-{document_id}.bib"'},
        )

    @app.get("/documents/{document_id}/export.ris")
    async def export_document_ris(document_id: int):
        row = db.fetch_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        if not row:
            raise HTTPException(404, "Document not found")
        return Response(
            documents_to_ris([row]),
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
                   d.source_type, pd.status, pd.exclusion_reason, d.why_saved, d.user_summary,
                   d.study_card_json
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
                "study_card_json",
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
            project_to_markdown(project, rows),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="project-{project_id}-evidence.md"'},
        )

    @app.get("/projects/{project_id}/export.bib")
    async def export_project_bibtex(project_id: int):
        rows = db.fetch_all(
            """SELECT d.* FROM project_documents pd JOIN documents d ON d.id = pd.document_id
               WHERE pd.project_id = ? ORDER BY d.publication_year DESC, d.title""",
            (project_id,),
        )
        return Response(
            documents_to_bibtex(rows),
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
            documents_to_ris(rows),
            media_type="application/x-research-info-systems",
            headers={"Content-Disposition": f'attachment; filename="project-{project_id}.ris"'},
        )

    @app.get("/topics", response_class=HTMLResponse)
    async def topics_page(request: Request):
        topic_counts: dict[str, int] = {}
        for row in db.fetch_all("SELECT keywords_json FROM documents"):
            try:
                keywords = json.loads(row["keywords_json"] or "[]")
            except json.JSONDecodeError:
                keywords = []
            for keyword in keywords:
                topic_counts[keyword] = topic_counts.get(keyword, 0) + 1
        topics = sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))
        return render_template("topics.html", context(request, topics=topics))

    @app.get("/topics/{topic}", response_class=HTMLResponse)
    async def topic_detail(request: Request, topic: str):
        results = search.search(topic, limit=80)
        years: dict[int, int] = {}
        source_type_counts: dict[str, int] = {}
        for result in results:
            if result.publication_year:
                years[result.publication_year] = years.get(result.publication_year, 0) + 1
            source_type_counts[result.source_type] = source_type_counts.get(result.source_type, 0) + 1
        return render_template(
            "topic.html",
            context(
                request,
                topic=topic,
                results=results,
                years=sorted(years.items()),
                source_type_counts=sorted(
                    source_type_counts.items(), key=lambda item: -item[1]
                ),
            ),
        )

    @app.get("/ask", response_class=HTMLResponse)
    async def ask_page(request: Request, project_id: str = ""):
        projects = db.fetch_all("SELECT id, name FROM projects ORDER BY name")
        return render_template(
            "ask.html",
            context(
                request,
                projects=projects,
                question="",
                answer=None,
                selected_project_id=_parse_int(project_id),
                primary_sources_only=False,
            ),
        )

    @app.post("/ask", response_class=HTMLResponse)
    async def ask_library(
        request: Request,
        question: str = Form(...),
        project_id: str = Form(""),
        primary_sources_only: bool = Form(False),
    ):
        parsed_project_id = _parse_int(project_id)
        answer = await qna.answer(
            question,
            project_id=parsed_project_id,
            primary_sources_only=primary_sources_only,
        )
        projects = db.fetch_all("SELECT id, name FROM projects ORDER BY name")
        return render_template(
            "ask.html",
            context(
                request,
                projects=projects,
                question=question,
                answer=answer,
                selected_project_id=parsed_project_id,
                primary_sources_only=primary_sources_only,
            ),
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
