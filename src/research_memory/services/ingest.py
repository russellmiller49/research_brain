from __future__ import annotations

import asyncio
import bisect
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.services.assets import AssetIntegrityError, AssetStore, StoredAsset
from research_memory.services.embeddings import Embedder, vector_to_blob
from research_memory.services.jobs import JobContext
from research_memory.services.metadata import (
    ExtractedPage,
    PdfExtractionError,
    enrich_from_crossref,
    enrich_from_pubmed,
    extract_pdf,
    infer_metadata,
)
from research_memory.utils import compact_whitespace, normalize_title, sha256_file


@dataclass(slots=True)
class IngestResult:
    status: str
    document_id: int | None
    file_name: str
    message: str
    error_code: str | None = None
    retryable: bool = False
    review_state: str = "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "document_id": self.document_id,
            "file_name": self.file_name,
            "message": self.message,
            "error_code": self.error_code,
            "retryable": self.retryable,
            "review_state": self.review_state,
        }


@dataclass(slots=True)
class Passage:
    page_number: int
    chunk_index: int
    text: str
    bounding_boxes: list[dict[str, float | str]]


def chunk_page(text: str, max_chars: int, overlap: int) -> list[str]:
    """Compatibility helper for plain text without layout geometry."""

    text = compact_whitespace(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        tentative_end = min(len(text), start + max_chars)
        end = tentative_end
        if tentative_end < len(text):
            boundary = max(
                text.rfind(". ", start + max_chars // 2, tentative_end),
                text.rfind("; ", start + max_chars // 2, tentative_end),
                text.rfind(" ", start + max_chars // 2, tentative_end),
            )
            if boundary > start:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_layout_page(page: ExtractedPage, max_chars: int, overlap: int) -> list[Passage]:
    body_blocks = [block for block in page.blocks if block.role == "body" and block.text]
    if not body_blocks:
        return [
            Passage(page.page_number, index, text, [])
            for index, text in enumerate(chunk_page(page.text, max_chars, overlap))
        ]

    chunks: list[Passage] = []
    current: list[Any] = []
    current_size = 0

    def emit() -> None:
        if not current:
            return
        text = "\n".join(block.text for block in current)
        boxes = [
            {
                "x0": block.x0,
                "y0": block.y0,
                "x1": block.x1,
                "y1": block.y1,
                "coordinate_space": "pdf_points",
            }
            for block in current
        ]
        chunks.append(Passage(page.page_number, len(chunks), text, boxes))

    for block in body_blocks:
        block_size = len(block.text) + (1 if current else 0)
        if current and current_size + block_size > max_chars:
            emit()
            overlap_blocks: list[Any] = []
            overlap_size = 0
            for prior in reversed(current):
                if overlap_blocks and overlap_size + len(prior.text) > overlap:
                    break
                overlap_blocks.insert(0, prior)
                overlap_size += len(prior.text) + 1
            current = overlap_blocks
            current_size = sum(len(item.text) + 1 for item in current)
        current.append(block)
        current_size += block_size
    emit()
    return chunks


class IngestionService:
    """Safe, idempotent PDF ingestion into managed immutable storage."""

    def __init__(
        self,
        db: Database,
        settings: Settings,
        embedder: Embedder,
        asset_store: AssetStore | None = None,
    ):
        self.db = db
        self.settings = settings
        self.embedder = embedder
        self.asset_store = asset_store or AssetStore(settings)

    async def ingest_path(
        self,
        path: str | Path,
        *,
        copy_into_library: bool = True,
        project_id: int | None = None,
        source_kind: str = "file",
        metadata_override: dict[str, Any] | None = None,
        external_source: str = "",
        external_key: str = "",
        external_version: int = 0,
        password: str | None = None,
        job: JobContext | None = None,
    ) -> IngestResult:
        del copy_into_library  # v0.2 always stores an immutable managed copy.
        source = Path(path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            return IngestResult(
                "error",
                None,
                source.name,
                "File does not exist.",
                error_code="missing_source",
                retryable=True,
                review_state="missing_source",
            )
        if source.suffix.lower() != ".pdf":
            return IngestResult(
                "skipped",
                None,
                source.name,
                "Only PDF files are indexed.",
                error_code="unsupported_file_type",
            )
        if source.stat().st_size > self.settings.max_upload_mb * 1024 * 1024:
            return IngestResult(
                "error",
                None,
                source.name,
                f"File exceeds the {self.settings.max_upload_mb} MB safety limit.",
                error_code="file_too_large",
                review_state="oversized",
            )

        if job:
            job.update("hashing")
        digest = await asyncio.to_thread(sha256_file, source)
        existing_file = self.db.fetch_one(
            self._existing_file_query(),
            (digest,),
        )
        if existing_file:
            return await self._reuse_existing_file(
                existing_file,
                source=source,
                digest=digest,
                source_kind=source_kind,
                project_id=project_id,
            )

        if job:
            job.update("copying")
        managed = await asyncio.to_thread(self.asset_store.store, source, digest)

        if job:
            job.update("extracting")
        try:
            extracted = await asyncio.to_thread(
                extract_pdf,
                managed.path,
                settings=self.settings,
                password=password,
            )
        except PdfExtractionError as exc:
            existing_file = self.db.fetch_one(self._existing_file_query(), (digest,))
            if existing_file:
                return await self._reuse_existing_file(
                    existing_file,
                    source=source,
                    digest=digest,
                    source_kind=source_kind,
                    project_id=project_id,
                )
            try:
                document_id = self._insert_review_document(
                    managed=managed,
                    source=source,
                    source_kind=source_kind,
                    external_source=external_source,
                    external_key=external_key,
                    external_version=external_version,
                    review_state=exc.code,
                    project_id=project_id,
                )
            except sqlite3.IntegrityError as integrity_error:
                duplicate = await self._reuse_after_sha_conflict(
                    integrity_error,
                    source=source,
                    digest=digest,
                    source_kind=source_kind,
                    project_id=project_id,
                )
                if duplicate:
                    return duplicate
                raise
            return IngestResult(
                "error",
                document_id,
                source.name,
                str(exc),
                error_code=exc.code,
                retryable=exc.retryable,
                review_state=exc.code,
            )

        metadata = infer_metadata(extracted, source)
        conflicts: list[dict[str, Any]] = []
        if metadata_override:
            merged = self._merge_metadata(metadata, metadata_override)
            conflicts.extend(self._metadata_conflicts(metadata, merged, source="import source"))
            metadata = merged
        if self.settings.enable_network_metadata:
            if job:
                job.update("metadata")
            local_metadata = dict(metadata)
            enriched = await enrich_from_crossref(metadata, mailto=self.settings.crossref_mailto)
            enriched = await enrich_from_pubmed(enriched, email=self.settings.crossref_mailto)
            conflicts.extend(
                self._metadata_conflicts(
                    local_metadata, enriched, source="online identifier lookup"
                )
            )
            metadata = enriched

        identifier_matches = self._identifier_matches(metadata)
        if len(identifier_matches) == 1:
            document_id = next(iter(identifier_matches))
            try:
                self._attach_file(
                    document_id,
                    managed,
                    source,
                    source_kind=source_kind,
                    external_source=external_source,
                    external_key=external_key,
                    external_version=external_version,
                    is_primary=False,
                )
            except sqlite3.IntegrityError as integrity_error:
                duplicate = await self._reuse_after_sha_conflict(
                    integrity_error,
                    source=source,
                    digest=digest,
                    source_kind=source_kind,
                    project_id=project_id,
                )
                if duplicate:
                    return duplicate
                raise
            self._add_to_project(document_id, project_id)
            return IngestResult(
                "version",
                document_id,
                source.name,
                "A matching DOI or PMID was found; this immutable file was attached as a version.",
            )

        title_matches = self._title_matches(metadata)
        review_state = "metadata_conflict" if conflicts else "ready"
        if metadata.pop("multi_article_suspected", False):
            review_state = "multi_article"
            conflicts.append(
                {
                    "kind": "multi_article",
                    "reason": "A later page begins a second abstract with a distinct DOI or PMID.",
                }
            )
        if identifier_matches or title_matches:
            if review_state == "ready":
                review_state = "possible_duplicate"
            conflicts.append(
                {
                    "kind": "possible_duplicate",
                    "article_ids": sorted(identifier_matches | title_matches),
                    "reason": (
                        "conflicting identifiers"
                        if len(identifier_matches) > 1
                        else "matching normalized title"
                    ),
                }
            )

        passages = [
            passage
            for page in extracted.layout_pages
            for passage in chunk_layout_page(
                page, self.settings.chunk_chars, self.settings.chunk_overlap
            )
        ]
        if job:
            job.update("embedding")
        vectors = await asyncio.to_thread(
            self._encode_in_batches, [passage.text for passage in passages]
        )
        if not any(page.text.strip() for page in extracted.layout_pages):
            extraction_status = "needs_ocr"
            review_state = "needs_ocr"
        elif any(page.extraction_method == "empty" for page in extracted.layout_pages):
            extraction_status = "partial"
            if review_state == "ready":
                review_state = "partial_extraction"
        else:
            extraction_status = "indexed"

        existing_file = self.db.fetch_one(self._existing_file_query(), (digest,))
        if existing_file:
            return await self._reuse_existing_file(
                existing_file,
                source=source,
                digest=digest,
                source_kind=source_kind,
                project_id=project_id,
            )
        if job:
            job.update("committing")
        try:
            document_id = self._insert_document(
                metadata=metadata,
                managed=managed,
                source=source,
                source_kind=source_kind,
                external_source=external_source,
                external_key=external_key,
                external_version=external_version,
                extraction_status=extraction_status,
                review_state=review_state,
                conflicts=conflicts,
                extracted=extracted,
                passages=passages,
                vectors=vectors,
                project_id=project_id,
            )
        except sqlite3.IntegrityError as integrity_error:
            duplicate = await self._reuse_after_sha_conflict(
                integrity_error,
                source=source,
                digest=digest,
                source_kind=source_kind,
                project_id=project_id,
            )
            if duplicate:
                return duplicate
            raise
        return IngestResult(
            "indexed",
            document_id,
            source.name,
            f"Indexed {len(passages)} passages across {extracted.page_count} pages"
            + (f", including {extracted.ocr_pages} OCR pages." if extracted.ocr_pages else "."),
            review_state=review_state,
        )

    @staticmethod
    def _existing_file_query() -> str:
        return """
            SELECT f.id, f.document_id, f.object_path, f.file_path,
                   f.availability, d.deleted_at
            FROM document_files f JOIN documents d ON d.id = f.document_id
            WHERE f.sha256 = ?
        """

    async def _reuse_existing_file(
        self,
        existing_file: Any,
        *,
        source: Path,
        digest: str,
        source_kind: str,
        project_id: int | None,
    ) -> IngestResult:
        document_id = int(existing_file["document_id"])
        try:
            self.asset_store.resolve(
                existing_file["object_path"] or existing_file["file_path"],
                digest,
            )
        except (AssetIntegrityError, FileNotFoundError, ValueError):
            repaired = await asyncio.to_thread(self.asset_store.store, source, digest)
            self.db.execute(
                """
                UPDATE document_files
                SET file_path = ?, object_path = ?, original_path = ?,
                    size_bytes = ?, availability = 'available',
                    source_kind = ?
                WHERE id = ?
                """,
                (
                    str(repaired.path),
                    str(repaired.path),
                    str(source),
                    repaired.size_bytes,
                    source_kind,
                    existing_file["id"],
                ),
            )
            self.db.execute(
                """
                UPDATE documents
                SET review_state = CASE
                        WHEN review_state = 'missing_source' THEN 'ready'
                        ELSE review_state
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (document_id,),
            )
        if existing_file["deleted_at"]:
            self.db.execute(
                """
                UPDATE documents
                SET deleted_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (document_id,),
            )
        self._add_to_project(document_id, project_id)
        return IngestResult(
            "duplicate",
            document_id,
            source.name,
            "Exact bytes already exist; the existing article was reused.",
        )

    async def _reuse_after_sha_conflict(
        self,
        error: sqlite3.IntegrityError,
        *,
        source: Path,
        digest: str,
        source_kind: str,
        project_id: int | None,
    ) -> IngestResult | None:
        if "document_files.sha256" not in str(error):
            return None
        existing_file = self.db.fetch_one(self._existing_file_query(), (digest,))
        if not existing_file:
            return None
        return await self._reuse_existing_file(
            existing_file,
            source=source,
            digest=digest,
            source_kind=source_kind,
            project_id=project_id,
        )

    async def ingest_folder(
        self,
        folder: str | Path,
        *,
        recursive: bool = True,
        copy_into_library: bool = True,
        project_id: int | None = None,
        limit: int | None = None,
        job: JobContext | None = None,
    ) -> list[IngestResult]:
        del copy_into_library
        root = Path(folder).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return [
                IngestResult(
                    "error",
                    None,
                    root.name,
                    "Folder does not exist.",
                    error_code="missing_source",
                    retryable=True,
                    review_state="missing_source",
                )
            ]
        iterator = root.rglob("*") if recursive else root.glob("*")
        paths = sorted(
            path for path in iterator if path.is_file() and path.suffix.lower() == ".pdf"
        )
        if limit is not None:
            paths = paths[:limit]
        start_index = 0
        if job:
            checkpoint = job.store.checkpoint(job.job_id)
            last_path = str(checkpoint.get("last_path") or "")
            if last_path:
                start_index = bisect.bisect_right([str(path) for path in paths], last_path)
        if job:
            job.update("discovering", current=start_index, total=len(paths))
        results: list[IngestResult] = []
        for index, pdf_path in enumerate(paths[start_index:], start=start_index):
            if job:
                job.raise_if_canceled()
            results.append(
                await self.ingest_path(
                    pdf_path,
                    project_id=project_id,
                    source_kind="folder",
                    job=job,
                )
            )
            if job:
                job.update(
                    "importing",
                    current=index + 1,
                    total=len(paths),
                    checkpoint={"last_path": str(pdf_path), "completed": index + 1},
                )
        return results

    async def handle_import_job(
        self, context: JobContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        path = payload["path"]
        source_kind = payload.get("source_kind", "folder")
        if source_kind == "file":
            result = await self.ingest_path(
                path,
                project_id=payload.get("project_id"),
                source_kind="file",
                job=context,
            )
            if result.status == "error":
                error = PdfExtractionError(
                    result.message,
                    code=result.error_code or "import_failed",
                    retryable=result.retryable,
                )
                raise error
            return {"results": [result.to_dict()]}
        results = await self.ingest_folder(
            path,
            recursive=bool(payload.get("recursive", True)),
            project_id=payload.get("project_id"),
            job=context,
        )
        for result in results:
            if result.status == "error":
                context.store.record_issue(
                    context.job_id,
                    result.file_name,
                    result.error_code or "import_failed",
                    retryable=result.retryable,
                )
        return {"results": [result.to_dict() for result in results]}

    async def reindex_document(
        self,
        document_id: int,
        *,
        password: str | None = None,
        job: JobContext | None = None,
    ) -> IngestResult:
        file_row = self.db.fetch_one(
            """
            SELECT * FROM document_files
            WHERE document_id = ? AND availability = 'available'
            ORDER BY is_primary DESC, id LIMIT 1
            """,
            (document_id,),
        )
        if not file_row:
            return IngestResult(
                "error",
                document_id,
                "",
                "No available managed PDF exists for this article.",
                error_code="missing_source",
                retryable=True,
                review_state="missing_source",
            )
        path = Path(file_row["object_path"] or file_row["file_path"])
        if not path.is_file():
            self.db.execute(
                """
                UPDATE document_files SET availability = 'missing' WHERE id = ?;
                """,
                (file_row["id"],),
            )
            return IngestResult(
                "error",
                document_id,
                file_row["file_name"],
                "The managed PDF is missing.",
                error_code="missing_source",
                retryable=True,
                review_state="missing_source",
            )
        extracted = await asyncio.to_thread(
            extract_pdf, path, settings=self.settings, password=password
        )
        passages = [
            passage
            for page in extracted.layout_pages
            for passage in chunk_layout_page(
                page, self.settings.chunk_chars, self.settings.chunk_overlap
            )
        ]
        vectors = await asyncio.to_thread(
            self._encode_in_batches, [passage.text for passage in passages]
        )
        metadata = infer_metadata(extracted, Path(file_row["file_name"]))
        if self.settings.enable_network_metadata:
            metadata = await enrich_from_crossref(
                metadata,
                mailto=self.settings.crossref_mailto,
            )
            metadata = await enrich_from_pubmed(
                metadata,
                email=self.settings.crossref_mailto,
            )
        if not any(page.text.strip() for page in extracted.layout_pages):
            extraction_status = "needs_ocr"
            review_state = "needs_ocr"
        elif any(page.extraction_method == "empty" for page in extracted.layout_pages):
            extraction_status = "partial"
            review_state = "partial_extraction"
        else:
            extraction_status = "indexed"
            review_state = "ready"
        if job:
            job.update("committing")
        with self.db.transaction() as connection:
            chunk_ids = [
                int(row[0])
                for row in connection.execute(
                    "SELECT id FROM document_chunks WHERE document_id = ?",
                    (document_id,),
                )
            ]
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                connection.execute(
                    f"DELETE FROM document_chunks_fts WHERE rowid IN ({placeholders})",
                    chunk_ids,
                )
            connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM document_pages WHERE document_id = ?", (document_id,))
            self._insert_derived(
                connection,
                document_id=document_id,
                file_id=int(file_row["id"]),
                extracted=extracted,
                passages=passages,
                vectors=vectors,
            )
            connection.execute(
                """
                UPDATE documents SET extraction_status = ?, review_state = ?, page_count = ?,
                    keywords_json = '[]', study_card_json = '{}',
                    title = CASE
                        WHEN metadata_status IN ('unavailable', 'local') THEN ? ELSE title
                    END,
                    normalized_title = CASE
                        WHEN metadata_status IN ('unavailable', 'local')
                        THEN ? ELSE normalized_title
                    END,
                    authors = CASE
                        WHEN metadata_status IN ('unavailable', 'local') THEN ? ELSE authors
                    END,
                    journal = CASE
                        WHEN metadata_status IN ('unavailable', 'local') THEN ? ELSE journal
                    END,
                    publication_year = CASE
                        WHEN metadata_status IN ('unavailable', 'local')
                        THEN ? ELSE publication_year
                    END,
                    doi = CASE
                        WHEN metadata_status IN ('unavailable', 'local') THEN ? ELSE doi
                    END,
                    pmid = CASE
                        WHEN metadata_status IN ('unavailable', 'local') THEN ? ELSE pmid
                    END,
                    abstract = CASE
                        WHEN metadata_status IN ('unavailable', 'local') THEN ? ELSE abstract
                    END,
                    source_type = CASE
                        WHEN metadata_status IN ('unavailable', 'local')
                        THEN ? ELSE source_type
                    END,
                    metadata_status = CASE
                        WHEN metadata_status IN ('unavailable', 'local')
                        THEN ? ELSE metadata_status
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    extraction_status,
                    review_state,
                    extracted.page_count,
                    metadata["title"],
                    metadata["normalized_title"],
                    metadata.get("authors", ""),
                    metadata.get("journal", ""),
                    metadata.get("publication_year"),
                    metadata.get("doi", ""),
                    metadata.get("pmid", ""),
                    metadata.get("abstract", ""),
                    metadata.get("source_type", "journal_article"),
                    metadata.get("metadata_status", "local"),
                    document_id,
                ),
            )
        return IngestResult(
            "indexed",
            document_id,
            file_row["file_name"],
            f"Rebuilt {len(passages)} passages.",
        )

    async def handle_reindex_job(
        self, context: JobContext, payload: dict[str, Any]
    ) -> dict[str, Any]:
        document_id = int(payload["document_id"])
        context.update("extracting", current=0, total=1)
        result = await self.reindex_document(
            document_id,
            password=payload.get("password"),
            job=context,
        )
        if result.status == "error":
            raise PdfExtractionError(
                result.message,
                code=result.error_code or "reindex_failed",
                retryable=result.retryable,
            )
        context.update("indexed", current=1, total=1)
        return result.to_dict()

    def _insert_review_document(
        self,
        *,
        managed: StoredAsset,
        source: Path,
        source_kind: str,
        external_source: str,
        external_key: str,
        external_version: int,
        review_state: str,
        project_id: int | None,
    ) -> int:
        title = compact_whitespace(source.stem.replace("_", " ").replace("-", " "))
        with self.db.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO documents (
                    title, normalized_title, extraction_status, metadata_status,
                    source_type, keywords_json, study_card_json, review_state,
                    external_source, external_key, external_version
                ) VALUES (?, ?, ?, 'unavailable', 'journal_article', '[]', '{}', ?, ?, ?, ?)
                """,
                (
                    title or "PDF requiring review",
                    normalize_title(title),
                    review_state,
                    review_state,
                    external_source,
                    external_key,
                    external_version,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return the review article identifier")
            document_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO document_files (
                    document_id, sha256, file_path, file_name, size_bytes,
                    is_primary, object_path, original_path, source_kind,
                    role, version_label, availability, external_source,
                    external_key, external_version
                ) VALUES (
                    ?, ?, ?, ?, ?, 1, ?, ?, ?, 'article', 'v1', 'available',
                    ?, ?, ?
                )
                """,
                (
                    document_id,
                    managed.sha256,
                    str(managed.path),
                    source.name,
                    managed.size_bytes,
                    str(managed.path),
                    str(source),
                    source_kind,
                    external_source,
                    external_key,
                    external_version,
                ),
            )
            if project_id:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO project_documents (project_id, document_id)
                    VALUES (?, ?)
                    """,
                    (project_id, document_id),
                )
        return document_id

    def migrate_legacy_assets(self) -> int:
        """Copy v0.1 file references into the managed store without altering sources."""

        rows = self.db.fetch_all(
            """
            SELECT * FROM document_files
            WHERE object_path = '' OR source_kind = 'legacy'
            ORDER BY id
            """
        )
        migrated = 0
        for row in rows:
            source = Path(row["file_path"])
            if not source.is_file():
                with self.db.transaction() as connection:
                    connection.execute(
                        "UPDATE document_files SET availability = 'missing' WHERE id = ?",
                        (row["id"],),
                    )
                    connection.execute(
                        """
                        UPDATE documents
                        SET review_state = 'missing_source', extraction_status = 'missing'
                        WHERE id = ?
                        """,
                        (row["document_id"],),
                    )
                continue
            actual_digest = sha256_file(source)
            if actual_digest != row["sha256"]:
                with self.db.transaction() as connection:
                    connection.execute(
                        """
                        UPDATE document_files SET availability = 'source_changed'
                        WHERE id = ?
                        """,
                        (row["id"],),
                    )
                    connection.execute(
                        """
                        UPDATE documents
                        SET review_state = 'source_changed',
                            extraction_status = 'reindex_required'
                        WHERE id = ?
                        """,
                        (row["document_id"],),
                    )
                continue
            managed = self.asset_store.store(source, actual_digest)
            self.db.execute(
                """
                UPDATE document_files
                SET file_path = ?, object_path = ?, original_path = ?,
                    source_kind = 'legacy_migration', availability = 'available'
                WHERE id = ?
                """,
                (str(managed.path), str(managed.path), str(source), row["id"]),
            )
            migrated += 1
        return migrated

    def _insert_document(
        self,
        *,
        metadata: dict[str, Any],
        managed: StoredAsset,
        source: Path,
        source_kind: str,
        external_source: str,
        external_key: str,
        external_version: int,
        extraction_status: str,
        review_state: str,
        conflicts: list[dict[str, Any]],
        extracted: Any,
        passages: list[Passage],
        vectors: np.ndarray,
        project_id: int | None,
    ) -> int:
        with self.db.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO documents (
                    title, normalized_title, authors, journal, publication_year,
                    doi, pmid, abstract, page_count, extraction_status,
                    metadata_status, source_type, keywords_json, study_card_json,
                    review_state, metadata_conflicts_json, external_source,
                    external_key, external_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '{}', ?, ?, ?, ?, ?)
                """,
                (
                    metadata["title"],
                    metadata["normalized_title"],
                    metadata.get("authors", ""),
                    metadata.get("journal", ""),
                    metadata.get("publication_year"),
                    metadata.get("doi", ""),
                    metadata.get("pmid", ""),
                    metadata.get("abstract", ""),
                    metadata.get("page_count", 0),
                    extraction_status,
                    metadata.get("metadata_status", "local"),
                    metadata.get("source_type", "journal_article"),
                    review_state,
                    json.dumps(conflicts),
                    external_source,
                    external_key,
                    external_version,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return the new article identifier")
            document_id = int(cursor.lastrowid)
            file_cursor = connection.execute(
                """
                INSERT INTO document_files (
                    document_id, sha256, file_path, file_name, size_bytes,
                    is_primary, object_path, original_path, source_kind,
                    role, version_label, availability, external_source,
                    external_key, external_version
                ) VALUES (
                    ?, ?, ?, ?, ?, 1, ?, ?, ?, 'article', 'v1', 'available',
                    ?, ?, ?
                )
                """,
                (
                    document_id,
                    managed.sha256,
                    str(managed.path),
                    source.name,
                    managed.size_bytes,
                    str(managed.path),
                    str(source),
                    source_kind,
                    external_source,
                    external_key,
                    external_version,
                ),
            )
            if file_cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return the new asset identifier")
            file_id = int(file_cursor.lastrowid)
            self._insert_derived(
                connection,
                document_id=document_id,
                file_id=file_id,
                extracted=extracted,
                passages=passages,
                vectors=vectors,
            )
            if project_id:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO project_documents (project_id, document_id)
                    VALUES (?, ?)
                    """,
                    (project_id, document_id),
                )
        return document_id

    def _insert_derived(
        self,
        connection: Any,
        *,
        document_id: int,
        file_id: int,
        extracted: Any,
        passages: list[Passage],
        vectors: np.ndarray,
    ) -> None:
        connection.executemany(
            """
            INSERT INTO document_pages (
                document_id, page_number, text, width, height,
                extraction_method, extraction_confidence, layout_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    document_id,
                    page.page_number,
                    page.text,
                    page.width,
                    page.height,
                    page.extraction_method,
                    page.confidence,
                    json.dumps([block.to_dict() for block in page.blocks]),
                )
                for page in extracted.layout_pages
            ],
        )
        for vector_index, passage in enumerate(passages):
            vector = vectors[vector_index] if len(vectors) else None
            cursor = connection.execute(
                """
                INSERT INTO document_chunks (
                    document_id, file_id, page_number, chunk_index, text,
                    bounding_boxes_json, embedding, embedding_dim,
                    embedding_backend, embedding_model, index_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    file_id,
                    passage.page_number,
                    passage.chunk_index,
                    passage.text,
                    json.dumps(passage.bounding_boxes),
                    vector_to_blob(vector) if vector is not None else None,
                    int(self.embedder.dimension) if vector is not None else 0,
                    self.embedder.backend_name if vector is not None else "",
                    self.settings.embedding_model if vector is not None else "",
                    self.settings.embedding_index_version,
                ),
            )
            chunk_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO document_chunks_fts
                    (rowid, text, document_id, page_number, chunk_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    passage.text,
                    document_id,
                    passage.page_number,
                    chunk_id,
                ),
            )

    def _encode_in_batches(self, texts: list[str], batch_size: int = 128) -> np.ndarray:
        if not texts:
            return np.empty((0, self.embedder.dimension), dtype=np.float32)
        batches = [
            self.embedder.encode(texts[start : start + batch_size])
            for start in range(0, len(texts), batch_size)
        ]
        return np.vstack(batches).astype(np.float32, copy=False)

    def _identifier_matches(self, metadata: dict[str, Any]) -> set[int]:
        matches: set[int] = set()
        doi = str(metadata.get("doi", "")).strip().lower()
        pmid = str(metadata.get("pmid", "")).strip()
        if doi:
            matches.update(
                int(row["id"])
                for row in self.db.fetch_all(
                    "SELECT id FROM documents WHERE doi = ? AND deleted_at IS NULL",
                    (doi,),
                )
            )
        if pmid:
            matches.update(
                int(row["id"])
                for row in self.db.fetch_all(
                    "SELECT id FROM documents WHERE pmid = ? AND deleted_at IS NULL",
                    (pmid,),
                )
            )
        return matches

    def _title_matches(self, metadata: dict[str, Any]) -> set[int]:
        normalized_title = str(metadata.get("normalized_title", ""))
        if len(normalized_title) < 24:
            return set()
        return {
            int(row["id"])
            for row in self.db.fetch_all(
                """
                SELECT id FROM documents
                WHERE normalized_title = ? AND deleted_at IS NULL
                """,
                (normalized_title,),
            )
        }

    @staticmethod
    def _merge_metadata(local: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "title",
            "authors",
            "journal",
            "publication_year",
            "doi",
            "pmid",
            "abstract",
            "source_type",
            "metadata_status",
        }
        merged = dict(local)
        for key in allowed:
            value = override.get(key)
            if value not in (None, ""):
                merged[key] = value
        merged["doi"] = str(merged.get("doi", "")).strip().lower()
        merged["pmid"] = str(merged.get("pmid", "")).strip()
        merged["normalized_title"] = normalize_title(str(merged.get("title", "")))
        return merged

    @staticmethod
    def _metadata_conflicts(
        local: dict[str, Any],
        candidate: dict[str, Any],
        *,
        source: str,
    ) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        for field_name in ("title", "publication_year", "doi", "pmid"):
            local_value = local.get(field_name)
            candidate_value = candidate.get(field_name)
            if local_value in (None, "") or candidate_value in (None, ""):
                continue
            left = (
                normalize_title(str(local_value))
                if field_name == "title"
                else str(local_value).strip().lower()
            )
            right = (
                normalize_title(str(candidate_value))
                if field_name == "title"
                else str(candidate_value).strip().lower()
            )
            if left != right:
                conflicts.append(
                    {
                        "kind": "metadata_conflict",
                        "field": field_name,
                        "local_value": local_value,
                        "candidate_value": candidate_value,
                        "source": source,
                        "reason": f"{source} disagrees with locally extracted {field_name}.",
                    }
                )
        return conflicts

    def _attach_file(
        self,
        document_id: int,
        managed: StoredAsset,
        source: Path,
        *,
        source_kind: str,
        external_source: str,
        external_key: str,
        external_version: int,
        is_primary: bool,
    ) -> None:
        count = int(
            self.db.scalar(
                "SELECT COUNT(*) FROM document_files WHERE document_id = ?",
                (document_id,),
            )
            or 0
        )
        self.db.execute(
            """
            INSERT INTO document_files (
                document_id, sha256, file_path, file_name, size_bytes, is_primary,
                object_path, original_path, source_kind, role, version_label,
                availability, external_source, external_key, external_version
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, 'article', ?, 'available', ?, ?, ?
            )
            """,
            (
                document_id,
                managed.sha256,
                str(managed.path),
                source.name,
                managed.size_bytes,
                int(is_primary),
                str(managed.path),
                str(source),
                source_kind or external_source or "file",
                f"v{count + 1}" + (f"-{external_version}" if external_version else ""),
                external_source,
                external_key,
                external_version,
            ),
        )
        if external_source and external_key:
            self.db.execute(
                """
                UPDATE documents
                SET external_source = CASE
                        WHEN external_source = '' THEN ? ELSE external_source
                    END,
                    external_key = CASE WHEN external_key = '' THEN ? ELSE external_key END,
                    external_version = MAX(external_version, ?)
                WHERE id = ?
                """,
                (external_source, external_key, external_version, document_id),
            )

    def _add_to_project(self, document_id: int, project_id: int | None) -> None:
        if project_id:
            self.db.execute(
                """
                INSERT OR IGNORE INTO project_documents (project_id, document_id)
                VALUES (?, ?)
                """,
                (project_id, document_id),
            )
