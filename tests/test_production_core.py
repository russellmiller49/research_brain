from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import httpx
import pytest
from conftest import make_pdf
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from research_memory.config import Settings
from research_memory.contracts import AnnotationCreate
from research_memory.db import Database
from research_memory.main import create_app
from research_memory.migrations import BASE_SCHEMA, CURRENT_SCHEMA_VERSION
from research_memory.services.annotations import AnnotationService
from research_memory.services.assets import AssetStore
from research_memory.services.backup import BackupError, BackupService
from research_memory.services.embeddings import (
    PINNED_MODEL_FILE,
    PINNED_MODEL_NAME,
    PINNED_MODEL_REPOSITORY,
    PINNED_MODEL_REVISION,
    PINNED_MODEL_SHA256,
)
from research_memory.services.jobs import BackgroundJobManager, JobContext, JobStore
from research_memory.services.library import LibraryService
from research_memory.services.metadata import extract_pdf
from research_memory.services.support import SupportBundleService
from research_memory.services.zotero import ZoteroImporter


def make_two_column_pdf(path: Path) -> Path:
    canvas = Canvas(str(path), pagesize=(612, 792))
    canvas.setTitle("Two Column Reading Order")
    for page_number in range(1, 4):
        canvas.drawString(54, 770, "Repeated Biomedical Journal Header")
        canvas.drawString(54, 730, f"Left {page_number} first sentence")
        canvas.drawString(54, 710, f"Left {page_number} second sentence")
        canvas.drawString(330, 730, f"Right {page_number} first sentence")
        canvas.drawString(330, 710, f"Right {page_number} second sentence")
        canvas.drawString(280, 25, f"Page {page_number}")
        canvas.showPage()
    canvas.save()
    return path


def encrypt_pdf(source: Path, destination: Path, password: str) -> Path:
    reader = PdfReader(source)
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.add_metadata(reader.metadata or {})
    writer.encrypt(password)
    with destination.open("wb") as handle:
        writer.write(handle)
    return destination


def test_numbered_migration_invalidates_v01_derived_data(tmp_path):
    database_path = tmp_path / "legacy.sqlite3"
    with (
        contextlib.closing(sqlite3.connect(database_path)) as connection,
        connection,
    ):
        connection.executescript(BASE_SCHEMA)
        cursor = connection.execute(
            """
            INSERT INTO documents(
                title, normalized_title, keywords_json, study_card_json
            ) VALUES ('Legacy paper', 'legacy paper', '["unsafe"]', '{"population":"wrong"}')
            """
        )
        document_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO document_files(
                document_id, sha256, file_path, file_name
            ) VALUES (?, ?, ?, ?)
            """,
            (document_id, "a" * 64, "/missing/legacy.pdf", "legacy.pdf"),
        )
        connection.execute(
            """
            INSERT INTO document_pages(document_id, page_number, text)
            VALUES (?, 1, 'interleaved flat text')
            """,
            (document_id,),
        )
    db = Database(database_path, tmp_path / "backups")
    applied = db.initialize()
    assert applied == list(range(1, CURRENT_SCHEMA_VERSION + 1))
    row = db.fetch_one("SELECT * FROM documents WHERE id = ?", (document_id,))
    assert row is not None
    assert row["keywords_json"] == "[]"
    assert row["study_card_json"] == "{}"
    assert row["extraction_status"] == "reindex_required"
    assert db.scalar("SELECT COUNT(*) FROM document_pages") == 0
    assert db.schema_version == CURRENT_SCHEMA_VERSION
    assert list((tmp_path / "backups").glob("pre-migration-*.sqlite3"))


def test_bundled_model_manifest_matches_runtime_pin():
    manifest_path = (
        Path(__file__).parents[1]
        / "desktop"
        / "src-tauri"
        / "resources"
        / "models"
        / "model-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text())
    assert manifest["model"] == PINNED_MODEL_NAME
    assert manifest["distribution_repository"] == PINNED_MODEL_REPOSITORY
    assert manifest["revision"] == PINNED_MODEL_REVISION
    assert manifest["onnx_file"] == PINNED_MODEL_FILE
    assert manifest["onnx_sha256"] == PINNED_MODEL_SHA256


def test_pdfium_orders_columns_and_removes_repeated_margins(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", auto_ocr=False)
    pdf = make_two_column_pdf(tmp_path / "columns.pdf")
    extracted = extract_pdf(pdf, settings=settings)
    first = extracted.pages[0]
    assert first.index("Left 1 first") < first.index("Left 1 second")
    assert first.index("Left 1 second") < first.index("Right 1 first")
    assert "Repeated Biomedical Journal Header" not in first
    assert "Page 1" not in first
    assert extracted.layout_pages[0].blocks
    assert all(block.x1 > block.x0 for block in extracted.layout_pages[0].blocks)
    assert all(
        0 <= block.x0 < block.x1 <= extracted.layout_pages[0].width
        and 0 <= block.y0 < block.y1 <= extracted.layout_pages[0].height
        for block in extracted.layout_pages[0].blocks
    )


@pytest.mark.asyncio
async def test_managed_asset_geometry_and_conservative_title_dedup(tmp_path, services):
    settings, db, ingestion, search = services
    first = make_pdf(
        tmp_path / "one.pdf",
        [
            "Shared but Nonidentifying Article Title\nAbstract\n"
            "A first manuscript about a distinctive catheter endpoint and 42 participants."
        ],
        title="Shared but Nonidentifying Article Title",
    )
    second = make_pdf(
        tmp_path / "two.pdf",
        [
            "Shared but Nonidentifying Article Title\nAbstract\n"
            "A second manuscript with different findings and no identifier."
        ],
        title="Shared but Nonidentifying Article Title",
    )
    first_result = await ingestion.ingest_path(first)
    second_result = await ingestion.ingest_path(second)
    assert first_result.document_id != second_result.document_id
    assert second_result.review_state == "possible_duplicate"
    assert db.scalar("SELECT COUNT(*) FROM documents") == 2

    asset = db.fetch_one(
        "SELECT * FROM document_files WHERE document_id = ?",
        (first_result.document_id,),
    )
    assert asset is not None
    object_path = Path(asset["object_path"])
    assert object_path.is_file()
    assert settings.objects_dir in object_path.parents
    assert object_path.name == f"{asset['sha256']}.pdf"
    assert asset["original_path"] == str(first.resolve())

    search.invalidate()
    hits = search.search("distinctive catheter endpoint")
    assert hits and hits[0].bounding_boxes
    page = db.fetch_one(
        """
        SELECT text FROM document_pages
        WHERE document_id = ? AND page_number = ?
        """,
        (hits[0].document_id, hits[0].page_number),
    )
    assert page is not None
    assert hits[0].snippet in page["text"]


@pytest.mark.asyncio
async def test_annotations_export_without_modifying_managed_asset(tmp_path, services):
    _, db, ingestion, _ = services
    source = make_pdf(
        tmp_path / "annotate.pdf",
        ["Annotation Export Paper\nAbstract\nA passage worth highlighting for later use."],
        title="Annotation Export Paper",
    )
    result = await ingestion.ingest_path(source)
    file_row = db.fetch_one(
        "SELECT * FROM document_files WHERE document_id = ?", (result.document_id,)
    )
    assert file_row is not None
    managed = Path(file_row["object_path"])
    before = managed.read_bytes()
    service = AnnotationService(db)
    primary_annotation = service.create(
        int(result.document_id),
        AnnotationCreate(
            asset_id=int(file_row["id"]),
            page_number=1,
            annotation_type="highlight",
            quad_points=[54, 680, 260, 680, 54, 665, 260, 665],
            selected_text="A passage worth highlighting",
            comment="Use in the discussion",
        ),
    )
    destination = tmp_path / "annotated.pdf"
    service.export_annotated_pdf(int(result.document_id), managed, destination)
    assert managed.read_bytes() == before
    reader = PdfReader(destination)
    assert reader.pages[0].get("/Annots")
    assert b"Use in the discussion" in service.export_xfdf(
        int(result.document_id),
        file_row["file_name"],
        file_id=int(file_row["id"]),
    )
    second_file = db.execute(
        """
        INSERT INTO document_files(
            document_id, sha256, file_path, file_name, object_path,
            source_kind, version_label, availability
        ) VALUES (?, ?, ?, ?, ?, 'file', 'v2', 'available')
        """,
        (
            result.document_id,
            "c" * 64,
            str(managed),
            "annotate-v2.pdf",
            str(managed),
        ),
    )
    service.create(
        int(result.document_id),
        AnnotationCreate(
            asset_id=int(second_file.lastrowid),
            page_number=1,
            annotation_type="comment",
            quad_points=[54, 640],
            selected_text="Alternate version text",
            comment="Secondary version note",
        ),
    )
    primary_xfdf = service.export_xfdf(
        int(result.document_id),
        file_row["file_name"],
        file_id=int(file_row["id"]),
    )
    assert primary_annotation.comment.encode() in primary_xfdf
    assert b"Secondary version note" not in primary_xfdf
    with pytest.raises(ValueError, match="outside the indexed PDF"):
        service.create(
            int(result.document_id),
            AnnotationCreate(
                asset_id=int(file_row["id"]),
                page_number=2,
                annotation_type="bookmark",
            ),
        )
    with pytest.raises(ValueError, match="complete PDF quad points"):
        service.create(
            int(result.document_id),
            AnnotationCreate(
                asset_id=int(file_row["id"]),
                page_number=1,
                annotation_type="highlight",
                selected_text="Incomplete geometry",
            ),
        )
    with pytest.raises(ValueError, match="coordinates are invalid"):
        service.create(
            int(result.document_id),
            AnnotationCreate(
                asset_id=int(file_row["id"]),
                page_number=1,
                annotation_type="comment",
                quad_points=[-1, 10],
            ),
        )


@pytest.mark.asyncio
async def test_encrypted_backup_restore_and_recoverable_trash(tmp_path, services):
    settings, db, ingestion, _ = services
    source = make_pdf(
        tmp_path / "backup.pdf",
        ["Backup Paper\nAbstract\nThis text must survive an encrypted round trip."],
        title="Backup Paper",
    )
    result = await ingestion.ingest_path(source)
    article_id = int(result.document_id)
    library = LibraryService(db)
    assert library.move_to_trash(article_id)
    assert library.restore(article_id)

    index_dir = settings.data_dir / "indexes"
    index_dir.mkdir(parents=True, exist_ok=True)
    stale_index = index_dir / "stale.usearch"
    stale_index.write_bytes(b"stale-vector-index")
    db.execute(
        """
        INSERT INTO index_state(name, version, item_count, max_item_id)
        VALUES ('vectors:test', 'stale', 1, 1)
        """
    )
    backup = BackupService(db, settings)
    archive = backup.create(tmp_path / "library.rmbak", "correct horse battery staple")
    manifest = backup.verify(archive, "correct horse battery staple")
    assert manifest["objects"]
    managed_path = Path(
        db.scalar("SELECT object_path FROM document_files WHERE document_id = ?", (article_id,))
    )
    managed_before = managed_path.read_bytes()
    unsafe_link = tmp_path / "unsafe-destination.rmbak"
    unsafe_link.symlink_to(managed_path)
    with pytest.raises(BackupError, match="outside the managed"):
        backup.create(unsafe_link, "correct horse battery staple")
    assert managed_path.read_bytes() == managed_before
    unsafe_link.unlink()

    db.execute("UPDATE documents SET title = 'Changed' WHERE id = ?", (article_id,))
    restored = backup.restore(archive, "correct horse battery staple")
    assert restored["documents"] == 1
    assert db.scalar("SELECT title FROM documents WHERE id = ?", (article_id,)) == "Backup Paper"
    assert db.scalar("SELECT COUNT(*) FROM index_state") == 0
    assert not stale_index.exists()

    managed_path.unlink()
    with pytest.raises(BackupError, match="Managed PDF is missing"):
        backup.create(tmp_path / "incomplete.rmbak", "correct horse battery staple")


def test_backup_rejects_untrusted_manifest_paths(tmp_path):
    settings = Settings(data_dir=tmp_path / "backup-data", embedding_backend="hash")
    settings.ensure_directories()
    db = Database(settings.database_path, settings.backups_dir)
    db.initialize()
    backup = BackupService(db, settings)
    database_copy = db.online_backup(tmp_path / "database.sqlite3")
    crafted_zip = tmp_path / "crafted.zip"
    with zipfile.ZipFile(crafted_zip, "w", compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": 1,
                    "schema_version": CURRENT_SCHEMA_VERSION,
                    "database_sha256": "a" * 64,
                    "objects": [{"sha256": "../../escape", "size_bytes": 3}],
                }
            ),
        )
        bundle.write(database_copy, "research_memory.sqlite3")
    encrypted = tmp_path / "crafted.rmbak"
    backup._encrypt(crafted_zip, encrypted, "correct horse battery staple")
    with pytest.raises(BackupError, match="invalid SHA-256"):
        backup.verify(encrypted, "correct horse battery staple")
    assert not (tmp_path / "escape.pdf").exists()


def test_trash_purge_never_unlinks_a_source_path(tmp_path):
    settings = Settings(data_dir=tmp_path / "trash-data", embedding_backend="hash")
    settings.ensure_directories()
    db = Database(settings.database_path, settings.backups_dir)
    db.initialize()
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-source-file")
    cursor = db.execute(
        """
        INSERT INTO documents(title, normalized_title, deleted_at)
        VALUES ('Legacy source', 'legacy source', datetime('now', '-31 days'))
        """
    )
    article_id = int(cursor.lastrowid)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    db.execute(
        """
        INSERT INTO document_files(
            document_id, sha256, file_path, object_path, original_path, file_name
        ) VALUES (?, ?, ?, ?, ?, 'source.pdf')
        """,
        (article_id, digest, str(source), str(source), str(source)),
    )
    library = LibraryService(db, AssetStore(settings))
    assert library.purge_expired() == 1
    assert source.is_file()


def test_job_recovery_and_private_ipc_boundary(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "api",
        ipc_token="session-secret",
        embedding_backend="hash",
        auto_ocr=False,
    )
    app = create_app(settings)
    jobs = JobStore(app.state.db)
    job_id = jobs.create("import", "folder label", {"path": "/redacted/internal"})
    jobs.record_issue(
        job_id,
        "oversized.pdf",
        "file_too_large",
        retryable=False,
    )
    jobs.mark_running(job_id)
    assert jobs.recover_interrupted() == 1
    assert jobs.get(job_id).status == "queued"
    assert jobs.get(job_id).issue_count == 1
    assert jobs.issues(job_id)[0].source_label == "oversized.pdf"

    with TestClient(app) as client:
        denied = client.get("/api/v1/status")
        assert denied.status_code == 401
        allowed = client.get(
            "/api/v1/status",
            headers={"X-Research-Memory-Token": "session-secret"},
        )
        assert allowed.status_code == 200
        assert allowed.json()["schema_version"] == CURRENT_SCHEMA_VERSION

    document = app.state.db.execute(
        "INSERT INTO documents(title, normalized_title) VALUES ('Token test', 'token test')"
    )
    app.state.db.execute(
        """
        INSERT INTO document_files(
            document_id, sha256, file_path, file_name, object_path
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            document.lastrowid,
            "b" * 64,
            "/managed/token-test.pdf",
            "token-test.pdf",
            "/managed/token-test.pdf",
        ),
    )
    app.state.db.execute(
        """
        INSERT INTO asset_access_tokens(token_hash, file_id, expires_at)
        SELECT ?, id, datetime('now', '+1 day') FROM document_files LIMIT 1
        """,
        ("a" * 64,),
    )
    restarted = create_app(settings)
    assert restarted.state.db.scalar("SELECT COUNT(*) FROM asset_access_tokens") == 0


def test_false_duplicate_import_failure_is_reconciled(tmp_path):
    db = Database(tmp_path / "jobs.sqlite3", tmp_path / "backups")
    db.initialize()
    source = tmp_path / "duplicate.pdf"
    source.write_bytes(b"%PDF-concurrent-source")
    document = db.execute(
        """
        INSERT INTO documents(title, normalized_title)
        VALUES ('Concurrent paper', 'concurrent paper')
        """
    )
    document_id = int(document.lastrowid)
    db.execute(
        """
        INSERT INTO document_files(
            document_id, sha256, file_path, object_path, original_path, file_name
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            hashlib.sha256(source.read_bytes()).hexdigest(),
            str(source),
            str(source),
            str(source),
            source.name,
        ),
    )
    jobs = JobStore(db)
    job_id = jobs.create(
        "import",
        source.name,
        {"path": str(source), "source_kind": "file"},
    )
    jobs.failed(
        job_id,
        error_code="integrityerror",
        message="UNIQUE constraint failed: document_files.sha256",
        retryable=False,
    )

    assert jobs.reconcile_duplicate_import_failures() == 1
    reconciled = jobs.get(job_id)
    assert reconciled is not None
    assert reconciled.status == "succeeded"
    assert reconciled.error_code is None
    output = json.loads(db.scalar("SELECT output_json FROM jobs WHERE id = ?", (job_id,)))
    assert output["results"][0]["document_id"] == document_id
    assert output["results"][0]["status"] == "duplicate"


@pytest.mark.asyncio
async def test_encrypted_malformed_and_multi_article_pdfs_become_review_records(tmp_path, services):
    _, db, ingestion, _ = services
    clear = make_pdf(
        tmp_path / "clear.pdf",
        ["Encrypted Paper\nAbstract\nThe secret passage survives decryption."],
        title="Encrypted Paper",
    )
    encrypted = encrypt_pdf(clear, tmp_path / "encrypted.pdf", "session-only-password")
    encrypted_result = await ingestion.ingest_path(encrypted)
    assert encrypted_result.document_id is not None
    assert encrypted_result.review_state == "password_required"
    assert (
        db.scalar(
            "SELECT COUNT(*) FROM document_chunks WHERE document_id = ?",
            (encrypted_result.document_id,),
        )
        == 0
    )

    unlocked = await ingestion.reindex_document(
        int(encrypted_result.document_id),
        password="session-only-password",
    )
    assert unlocked.status == "indexed"
    assert (
        db.scalar(
            "SELECT review_state FROM documents WHERE id = ?",
            (encrypted_result.document_id,),
        )
        == "ready"
    )

    malformed = tmp_path / "malformed.pdf"
    malformed.write_bytes(b"%PDF-1.7\nnot a valid PDF")
    malformed_result = await ingestion.ingest_path(malformed)
    assert malformed_result.document_id is not None
    assert malformed_result.review_state == "malformed_pdf"

    empty = tmp_path / "empty.pdf"
    empty_writer = PdfWriter()
    with empty.open("wb") as handle:
        empty_writer.write(handle)
    empty_result = await ingestion.ingest_path(empty)
    assert empty_result.document_id is not None
    assert empty_result.review_state == "malformed_pdf"

    bundle = make_pdf(
        tmp_path / "bundle.pdf",
        [
            "First Bundled Article\nAbstract\nFirst result. DOI: 10.1234/bundle.first",
            "Second Bundled Article\nAbstract\nSecond result. DOI: 10.1234/bundle.second",
        ],
        title="First Bundled Article",
    )
    bundle_result = await ingestion.ingest_path(bundle)
    assert bundle_result.review_state == "multi_article"
    conflicts = json.loads(
        db.scalar(
            "SELECT metadata_conflicts_json FROM documents WHERE id = ?",
            (bundle_result.document_id,),
        )
    )
    assert any(conflict["kind"] == "multi_article" for conflict in conflicts)

    conflict_source = make_pdf(
        tmp_path / "metadata-conflict.pdf",
        ["Locally Extracted Trial Title\nAbstract\nA metadata reconciliation test."],
        title="Locally Extracted Trial Title",
    )
    conflict_result = await ingestion.ingest_path(
        conflict_source,
        metadata_override={"title": "Imported Catalog Trial Title"},
    )
    assert conflict_result.review_state == "metadata_conflict"


@pytest.mark.asyncio
async def test_folder_job_resumes_after_last_checkpoint(tmp_path, services):
    _, db, ingestion, _ = services
    folder = tmp_path / "resume"
    folder.mkdir()
    paths = [
        make_pdf(
            folder / f"{index}.pdf",
            [f"Resume Paper {index}\nAbstract\nUnique checkpoint text {index}."],
            title=f"Resume Paper {index}",
        )
        for index in range(3)
    ]
    jobs = JobStore(db)
    job_id = jobs.create("import", "resume", {"path": str(folder)})
    jobs.progress(
        job_id,
        stage="importing",
        current=2,
        total=3,
        checkpoint={"last_path": str(paths[1]), "completed": 2},
    )
    results = await ingestion.ingest_folder(folder, job=JobContext(job_id, jobs))
    assert [result.file_name for result in results] == ["2.pdf"]
    assert db.scalar("SELECT COUNT(*) FROM documents") == 1


@pytest.mark.asyncio
async def test_exclusive_model_job_does_not_overlap_ingestion(tmp_path):
    db = Database(tmp_path / "jobs.sqlite3", tmp_path / "backups")
    db.initialize()
    jobs = JobStore(db)
    manager = BackgroundJobManager(jobs, worker_count=2)
    normal_started = asyncio.Event()
    release_normal = asyncio.Event()
    exclusive_started = asyncio.Event()
    release_exclusive = asyncio.Event()
    timeline: list[str] = []

    async def normal_handler(_context, payload):
        label = str(payload["label"])
        timeline.append(f"{label}:start")
        if label == "first":
            normal_started.set()
            await release_normal.wait()
        timeline.append(f"{label}:end")
        return {}

    async def exclusive_handler(_context, _payload):
        timeline.append("model:start")
        exclusive_started.set()
        await release_exclusive.wait()
        timeline.append("model:end")
        return {}

    manager.register("import", normal_handler)
    manager.register("install_model", exclusive_handler, exclusive=True)
    jobs.create("import", "first", {"label": "first"})
    jobs.create("install_model", "model", {})
    jobs.create("import", "second", {"label": "second"})
    await manager.start()
    try:
        await asyncio.wait_for(normal_started.wait(), timeout=2)
        release_normal.set()
        await asyncio.wait_for(exclusive_started.wait(), timeout=2)
        await asyncio.sleep(0)
        assert "second:start" not in timeline
        release_exclusive.set()
        await asyncio.wait_for(manager.queue.join(), timeout=2)
    finally:
        await manager.stop()
    assert timeline == [
        "first:start",
        "first:end",
        "model:start",
        "model:end",
        "second:start",
        "second:end",
    ]


@pytest.mark.asyncio
async def test_desktop_api_strict_inputs_pagination_and_asset_origin(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "desktop-api",
        ipc_token="private-token",
        allow_legacy_web=False,
        embedding_backend="hash",
        auto_ocr=False,
    )
    app = create_app(settings)
    source = make_pdf(
        tmp_path / "boundary.pdf",
        ["Boundary Paper\nAbstract\nA private passage with exact page provenance."],
        title="Boundary Paper",
    )
    result = await app.state.ingestion.ingest_path(source)
    asset_id = int(
        app.state.db.scalar(
            "SELECT id FROM document_files WHERE document_id = ?",
            (result.document_id,),
        )
    )
    headers = {"X-Research-Memory-Token": "private-token"}
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/docs").status_code == 404
        assert (
            client.post(
                "/api/v1/search",
                headers=headers,
                json={"text": "private passage", "unexpected": True},
            ).status_code
            == 422
        )
        page = client.get(
            "/api/v1/articles/page?limit=1&offset=0",
            headers=headers,
        )
        assert page.status_code == 200
        assert page.json()["total"] == 1
        assert len(page.json()["items"]) == 1

        updated = client.patch(
            f"/api/v1/articles/{result.document_id}",
            headers=headers,
            json={"title": "A manually curated title"},
        )
        assert updated.status_code == 200
        assert (
            app.state.db.scalar(
                "SELECT metadata_status FROM documents WHERE id = ?",
                (result.document_id,),
            )
            == "user"
        )

        app.state.db.execute(
            """
            UPDATE documents
            SET review_state = 'possible_duplicate',
                metadata_conflicts_json = '[{"kind":"possible_duplicate"}]'
            WHERE id = ?
            """,
            (result.document_id,),
        )
        review = client.post(
            f"/api/v1/articles/{result.document_id}/review",
            headers=headers,
            json={"resolution": "accept_as_separate_article"},
        )
        assert review.status_code == 200
        assert review.json()["review_state"] == "ready"
        assert (
            app.state.db.scalar(
                "SELECT COUNT(*) FROM review_decisions WHERE document_id = ?",
                (result.document_id,),
            )
            == 1
        )

        capability = client.post(
            f"/api/v1/assets/{asset_id}/access",
            headers=headers,
        )
        assert capability.status_code == 200
        asset_url = capability.json()["url"]
        assert client.get(asset_url, headers={"Origin": "https://evil.example"}).status_code == 403
        allowed = client.get(asset_url, headers={"Origin": "tauri://localhost"})
        assert allowed.status_code == 200
        assert allowed.headers["access-control-allow-origin"] == "tauri://localhost"
        assert "*" not in allowed.headers["access-control-allow-origin"]

        deleted = client.delete(
            f"/api/v1/articles/{result.document_id}",
            headers=headers,
        )
        assert deleted.status_code == 204
        trash = client.get("/api/v1/trash", headers=headers)
        assert trash.status_code == 200
        assert set(trash.json()[0]) == {"id", "title", "deleted_at", "purge_after"}
        assert "path" not in json.dumps(trash.json()).lower()
        restored = client.post(
            f"/api/v1/trash/{result.document_id}/restore",
            headers=headers,
        )
        assert restored.status_code == 204


def test_bulk_project_add_is_atomic_idempotent_and_preserves_existing_status(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "bulk-project-api",
        ipc_token="private-token",
        allow_legacy_web=False,
        embedding_backend="hash",
        auto_ocr=False,
    )
    app = create_app(settings)
    project_id = int(
        app.state.db.execute("INSERT INTO projects(name) VALUES ('Airway review')").lastrowid
    )
    article_ids = [
        int(
            app.state.db.execute(
                "INSERT INTO documents(title, normalized_title) VALUES (?, ?)",
                (f"Paper {index}", f"paper {index}"),
            ).lastrowid
        )
        for index in range(1, 4)
    ]
    app.state.db.execute(
        """
        INSERT INTO project_documents(project_id, document_id, status)
        VALUES (?, ?, 'included')
        """,
        (project_id, article_ids[0]),
    )
    headers = {"X-Research-Memory-Token": "private-token"}

    with TestClient(app) as client:
        added = client.post(
            f"/api/v1/projects/{project_id}/articles/bulk",
            headers=headers,
            json={"article_ids": [article_ids[0], article_ids[1], article_ids[1]]},
        )
        assert added.status_code == 200
        assert added.json() == {
            "project_id": project_id,
            "requested": 2,
            "added": 1,
            "already_present": 1,
        }
        assert (
            app.state.db.scalar(
                """
                SELECT status FROM project_documents
                WHERE project_id = ? AND document_id = ?
                """,
                (project_id, article_ids[0]),
            )
            == "included"
        )

        rejected = client.post(
            f"/api/v1/projects/{project_id}/articles/bulk",
            headers=headers,
            json={"article_ids": [article_ids[2], 999_999]},
        )
        assert rejected.status_code == 404
        assert (
            app.state.db.scalar(
                """
                SELECT COUNT(*) FROM project_documents
                WHERE project_id = ? AND document_id = ?
                """,
                (project_id, article_ids[2]),
            )
            == 0
        )
        assert (
            app.state.db.scalar(
                "SELECT COUNT(*) FROM project_documents WHERE project_id = ?",
                (project_id,),
            )
            == 2
        )


@pytest.mark.asyncio
async def test_password_is_ephemeral_and_support_bundle_is_redacted(tmp_path, services):
    settings, db, ingestion, _ = services
    source = make_pdf(
        tmp_path / "private-filename.pdf",
        ["Secret Trial Title\nAbstract\nHighly confidential passage text."],
        title="Secret Trial Title",
    )
    result = await ingestion.ingest_path(source)
    document_id = int(result.document_id)
    db.execute(
        "UPDATE documents SET why_saved = ? WHERE id = ?",
        ("private note that must never be exported in diagnostics", document_id),
    )
    db.execute(
        "INSERT INTO notes(document_id, body) VALUES (?, ?)",
        (document_id, "private note body"),
    )
    jobs = JobStore(db)
    job_id = jobs.create("reindex", "redacted article", {"document_id": document_id})
    manager = BackgroundJobManager(jobs)
    manager.enqueue(job_id, sensitive_input={"password": "session-only-password"})
    persisted = db.scalar("SELECT input_json FROM jobs WHERE id = ?", (job_id,))
    assert "session-only-password" not in persisted
    await manager.stop()
    assert manager._sensitive_inputs == {}

    bundle = SupportBundleService(db, settings).create(tmp_path / "support.zip")
    with zipfile.ZipFile(bundle) as archive:
        assert archive.namelist() == ["support.json"]
        payload = archive.read("support.json")
    for secret in (
        b"Secret Trial Title",
        b"private-filename.pdf",
        b"Highly confidential passage text",
        b"private note body",
        b"private note that must never",
        str(source).encode(),
    ):
        assert secret not in payload


@pytest.mark.asyncio
async def test_zotero_local_api_is_path_safe_and_reimport_idempotent(
    tmp_path, services, monkeypatch
):
    _, db, ingestion, _ = services
    source = make_pdf(
        tmp_path / "zotero-paper.pdf",
        ["Zotero Paper\nAbstract\nA stable attachment for an idempotency test."],
        title="Zotero Paper",
    )
    pdf_bytes = source.read_bytes()
    parent = {
        "key": "ITEM1",
        "version": 8,
        "data": {
            "itemType": "journalArticle",
            "title": "Zotero Paper",
            "creators": [{"firstName": "Ada", "lastName": "Lovelace"}],
            "publicationTitle": "Journal of Local Research",
            "date": "2025",
            "DOI": "10.1234/zotero.1",
            "collections": ["COLL1"],
        },
    }
    attachment = {
        "key": "ATTACH1",
        "version": 4,
        "data": {
            "itemType": "attachment",
            "contentType": "application/pdf",
            "parentItem": "ITEM1",
            "filename": "zotero-paper.pdf",
        },
    }
    annotation = {
        "key": "ANN1",
        "version": 2,
        "data": {
            "itemType": "annotation",
            "parentItem": "ATTACH1",
            "annotationText": "A local Zotero annotation",
        },
    }
    collection = {
        "key": "COLL1",
        "version": 3,
        "data": {"name": "Design Partners", "parentCollection": False},
    }
    download_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal download_count
        assert request.url.host == "127.0.0.1"
        assert request.url.port == 23119
        if request.url.path == "/api/users/0/items":
            return httpx.Response(
                200,
                json=[parent, attachment, annotation],
                headers={"Total-Results": "3"},
            )
        if request.url.path == "/api/users/0/collections":
            return httpx.Response(
                200,
                json=[collection],
                headers={"Total-Results": "1"},
            )
        if request.url.path == "/api/users/0/items/ATTACH1/file":
            download_count += 1
            return httpx.Response(
                200,
                content=pdf_bytes,
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Length": str(len(pdf_bytes)),
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(
        "research_memory.services.zotero.httpx.AsyncClient",
        client_factory,
    )
    importer = ZoteroImporter(db, ingestion)

    first = await importer.sync()
    assert first["imported"] == 1
    assert first["errors"] == 0
    assert download_count == 1

    second = await importer.sync()
    assert second["unchanged"] == 1
    assert second["errors"] == 0
    assert download_count == 1
    assert db.scalar("SELECT COUNT(*) FROM documents") == 1
    assert db.scalar("SELECT COUNT(*) FROM document_files") == 1
    relationship = db.fetch_one(
        """
        SELECT parent_item_key, document_id, file_id, external_version
        FROM external_attachments
        WHERE external_key = 'ATTACH1'
        """
    )
    assert relationship is not None
    assert relationship["parent_item_key"] == "ITEM1"
    assert relationship["document_id"] is not None
    assert relationship["file_id"] is not None
    assert relationship["external_version"] == 4
    assert db.scalar("SELECT COUNT(*) FROM external_item_collections WHERE item_key = 'ITEM1'") == 1
    assert db.scalar("SELECT COUNT(*) FROM external_annotations WHERE document_id IS NOT NULL") == 1

    attachment["version"] = 5
    third = await importer.sync()
    assert third["imported"] == 1
    assert third["errors"] == 0
    assert download_count == 2
    assert db.scalar("SELECT COUNT(*) FROM documents") == 1
    assert db.scalar("SELECT COUNT(*) FROM document_files") == 1
    assert (
        db.scalar(
            "SELECT external_version FROM external_attachments WHERE external_key = 'ATTACH1'"
        )
        == 5
    )

    fourth = await importer.sync()
    assert fourth["unchanged"] == 1
    assert download_count == 2
