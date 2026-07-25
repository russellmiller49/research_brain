from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.services.embeddings import Embedder, vector_to_blob
from research_memory.services.metadata import (
    PdfExtractionError,
    enrich_from_crossref,
    extract_pdf,
    infer_metadata,
)
from research_memory.services.study import build_study_card, card_to_json, extract_keywords
from research_memory.utils import compact_whitespace, safe_filename, sha256_file


@dataclass(slots=True)
class IngestResult:
    status: str
    document_id: int | None
    file_name: str
    message: str


def chunk_page(text: str, max_chars: int, overlap: int) -> list[str]:
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


class IngestionService:
    def __init__(self, db: Database, settings: Settings, embedder: Embedder):
        self.db = db
        self.settings = settings
        self.embedder = embedder

    async def ingest_path(
        self,
        path: str | Path,
        *,
        copy_into_library: bool = False,
        project_id: int | None = None,
    ) -> IngestResult:
        source = Path(path).expanduser().resolve()
        if not source.exists() or not source.is_file():
            return IngestResult("error", None, source.name, "File does not exist.")
        if source.suffix.lower() != ".pdf":
            return IngestResult("skipped", None, source.name, "Only PDF files are indexed.")
        if source.stat().st_size > self.settings.max_upload_mb * 1024 * 1024:
            return IngestResult(
                "error",
                None,
                source.name,
                f"File exceeds the {self.settings.max_upload_mb} MB safety limit.",
            )

        digest = await asyncio.to_thread(sha256_file, source)
        existing_file = self.db.fetch_one(
            "SELECT document_id FROM document_files WHERE sha256 = ?", (digest,)
        )
        if existing_file:
            document_id = int(existing_file["document_id"])
            self._add_to_project(document_id, project_id)
            return IngestResult(
                "duplicate",
                document_id,
                source.name,
                "Exact duplicate already indexed; the existing article was reused.",
            )

        try:
            extracted = await asyncio.to_thread(extract_pdf, source)
        except PdfExtractionError as exc:
            return IngestResult("error", None, source.name, str(exc))

        metadata = infer_metadata(extracted, source)
        if self.settings.enable_crossref:
            metadata = await enrich_from_crossref(
                metadata, mailto=self.settings.crossref_mailto
            )

        duplicate = self._find_probable_duplicate(metadata)
        if duplicate:
            document_id = int(duplicate["id"])
            managed_path = self._store_file(source, digest) if copy_into_library else source
            self._attach_file(document_id, managed_path, source.name, digest, is_primary=False)
            self._add_to_project(document_id, project_id)
            return IngestResult(
                "version",
                document_id,
                source.name,
                "A probable alternate version was attached to the existing article.",
            )

        keywords = extract_keywords(
            metadata["title"], metadata.get("abstract", ""), extracted.pages
        )
        study_card = build_study_card(
            metadata["title"],
            metadata.get("abstract", ""),
            extracted.pages,
            metadata.get("source_type", "journal_article"),
        )
        has_substantial_text = sum(len(page.strip()) for page in extracted.pages) >= 300
        extraction_status = "indexed" if has_substantial_text else "needs_ocr"

        page_chunks: list[tuple[int, int, str]] = []
        for page_number, page_text in enumerate(extracted.pages, start=1):
            for chunk_index, chunk in enumerate(
                chunk_page(page_text, self.settings.chunk_chars, self.settings.chunk_overlap)
            ):
                page_chunks.append((page_number, chunk_index, chunk))

        vectors = self.embedder.encode([item[2] for item in page_chunks])
        managed_path = self._store_file(source, digest) if copy_into_library else source

        try:
            with self.db.transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO documents (
                        title, normalized_title, authors, journal, publication_year,
                        doi, pmid, abstract, page_count, extraction_status,
                        metadata_status, source_type, keywords_json, study_card_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        json.dumps(keywords, ensure_ascii=False),
                        card_to_json(study_card),
                    ),
                )
                document_id = int(cursor.lastrowid)
                connection.execute(
                    """
                    INSERT INTO document_files
                        (document_id, sha256, file_path, file_name, size_bytes, is_primary)
                    VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (
                        document_id,
                        digest,
                        str(managed_path),
                        source.name,
                        managed_path.stat().st_size,
                    ),
                )
                connection.executemany(
                    "INSERT INTO document_pages (document_id, page_number, text) VALUES (?, ?, ?)",
                    [
                        (document_id, page_number, page_text)
                        for page_number, page_text in enumerate(extracted.pages, start=1)
                    ],
                )
                for vector_index, (page_number, chunk_index, text) in enumerate(page_chunks):
                    vector = vectors[vector_index] if len(vectors) else None
                    cursor = connection.execute(
                        """
                        INSERT INTO document_chunks (
                            document_id, page_number, chunk_index, text, embedding,
                            embedding_dim, embedding_backend
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            document_id,
                            page_number,
                            chunk_index,
                            text,
                            vector_to_blob(vector) if vector is not None else None,
                            int(self.embedder.dimension) if vector is not None else 0,
                            self.embedder.backend_name if vector is not None else "",
                        ),
                    )
                    chunk_id = int(cursor.lastrowid)
                    connection.execute(
                        """
                        INSERT INTO document_chunks_fts
                            (rowid, text, document_id, page_number, chunk_id)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (chunk_id, text, document_id, page_number, chunk_id),
                    )
                if project_id:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO project_documents (project_id, document_id)
                        VALUES (?, ?)
                        """,
                        (project_id, document_id),
                    )
        except Exception:
            if copy_into_library and managed_path.exists():
                managed_path.unlink(missing_ok=True)
            raise

        return IngestResult(
            "indexed",
            document_id,
            source.name,
            f"Indexed {len(page_chunks)} searchable passages across {extracted.page_count} pages.",
        )

    async def ingest_folder(
        self,
        folder: str | Path,
        *,
        recursive: bool = True,
        copy_into_library: bool = False,
        project_id: int | None = None,
        limit: int | None = None,
    ) -> list[IngestResult]:
        root = Path(folder).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return [IngestResult("error", None, root.name, "Folder does not exist.")]
        iterator = root.rglob("*.pdf") if recursive else root.glob("*.pdf")
        paths = sorted(iterator)
        if limit is not None:
            paths = paths[:limit]
        results: list[IngestResult] = []
        for path in paths:
            results.append(
                await self.ingest_path(
                    path, copy_into_library=copy_into_library, project_id=project_id
                )
            )
        return results

    def _find_probable_duplicate(self, metadata: dict[str, Any]):
        doi = metadata.get("doi", "")
        if doi:
            match = self.db.fetch_one("SELECT id FROM documents WHERE doi = ?", (doi,))
            if match:
                return match
        normalized_title = metadata.get("normalized_title", "")
        if len(normalized_title) >= 24:
            return self.db.fetch_one(
                "SELECT id FROM documents WHERE normalized_title = ?", (normalized_title,)
            )
        return None

    def _store_file(self, source: Path, digest: str) -> Path:
        destination = self.settings.library_dir / f"{digest[:12]}-{safe_filename(source.name)}"
        if not destination.exists():
            shutil.copy2(source, destination)
        return destination

    def _attach_file(
        self,
        document_id: int,
        path: Path,
        original_name: str,
        digest: str,
        *,
        is_primary: bool,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO document_files
                (document_id, sha256, file_path, file_name, size_bytes, is_primary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                digest,
                str(path),
                original_name,
                path.stat().st_size,
                int(is_primary),
            ),
        )

    def _add_to_project(self, document_id: int, project_id: int | None) -> None:
        if project_id:
            self.db.execute(
                "INSERT OR IGNORE INTO project_documents (project_id, document_id) VALUES (?, ?)",
                (project_id, document_id),
            )
