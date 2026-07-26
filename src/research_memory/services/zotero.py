from __future__ import annotations

import hashlib
import json
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from research_memory.db import Database
from research_memory.services.ingest import IngestionService, IngestResult
from research_memory.services.jobs import JobContext
from research_memory.utils import compact_whitespace, safe_filename, sha256_file


class ZoteroImportError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ZoteroImporter:
    """One-way import through Zotero's supported read-only local HTTP API."""

    def __init__(self, db: Database, ingestion: IngestionService):
        self.db = db
        self.ingestion = ingestion

    async def sync(
        self,
        *,
        base_url: str = "http://127.0.0.1:23119/api",
        job: JobContext | None = None,
    ) -> dict[str, int]:
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port != 23119
            or parsed.path.rstrip("/") != "/api"
            or parsed.query
            or parsed.fragment
        ):
            raise ZoteroImportError(
                "The Zotero beta connector accepts only the local read-only API.",
                code="invalid_zotero_endpoint",
            )
        source_id = self._ensure_source(base_url)
        headers = {
            "Zotero-API-Version": "3",
            "User-Agent": "ResearchMemory/0.2 (local read-only importer)",
        }
        timeout = httpx.Timeout(30, connect=5)
        try:
            async with httpx.AsyncClient(
                base_url=f"{base_url.rstrip('/')}/",
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                if job:
                    job.update("reading_zotero")
                items = await self._fetch_all(client, "users/0/items")
                collections = await self._fetch_all(client, "users/0/collections")
                parents = {
                    item.get("key", ""): item
                    for item in items
                    if item.get("data", {}).get("itemType")
                    not in {"attachment", "annotation", "note"}
                }
                attachments = [
                    item
                    for item in items
                    if item.get("data", {}).get("itemType") == "attachment"
                    and item.get("data", {}).get("contentType") == "application/pdf"
                ]
                annotations = [
                    item for item in items if item.get("data", {}).get("itemType") == "annotation"
                ]
                self._store_collections(source_id, collections, parents)
                stats = {
                    "items": len(parents),
                    "attachments": len(attachments),
                    "annotations": len(annotations),
                    "imported": 0,
                    "unchanged": 0,
                    "errors": 0,
                }
                if job:
                    job.update("importing_zotero", current=0, total=len(attachments))
                attachment_documents: dict[str, int] = {}
                for index, attachment in enumerate(attachments):
                    if job:
                        job.raise_if_canceled()
                    attachment_key = str(attachment.get("key", ""))
                    data = attachment.get("data", {})
                    version = int(attachment.get("version") or data.get("version") or 0)
                    existing = self.db.fetch_one(
                        """
                        SELECT document_id, external_version FROM external_attachments
                        WHERE source_id = ? AND external_key = ?
                        """,
                        (source_id, attachment_key),
                    )
                    if (
                        existing
                        and existing["document_id"] is not None
                        and int(existing["external_version"] or 0) >= version
                    ):
                        stats["unchanged"] += 1
                        attachment_documents[attachment_key] = int(existing["document_id"])
                        if job:
                            job.update(
                                "importing_zotero",
                                current=index + 1,
                                total=len(attachments),
                                checkpoint={"attachment_key": attachment_key},
                            )
                        continue
                    parent_key = str(data.get("parentItem", ""))
                    parent = parents.get(parent_key, {})
                    filename = safe_filename(
                        str(data.get("filename") or data.get("title") or f"{attachment_key}.pdf")
                    )
                    try:
                        result, digest = await self._download_and_ingest(
                            client,
                            attachment,
                            parent,
                        )
                    except Exception as exc:
                        stats["errors"] += 1
                        if job:
                            job.store.record_issue(
                                job.job_id,
                                filename,
                                str(getattr(exc, "code", exc.__class__.__name__.lower())),
                                retryable=bool(getattr(exc, "retryable", False)),
                            )
                    else:
                        if result.document_id is not None:
                            attachment_documents[attachment_key] = result.document_id
                            self._store_external_attachment(
                                source_id,
                                attachment,
                                parent_key,
                                result.document_id,
                                digest,
                            )
                            self._store_external_item(
                                source_id, parent or attachment, result.document_id
                            )
                            if result.status == "error":
                                stats["errors"] += 1
                                if job:
                                    job.store.record_issue(
                                        job.job_id,
                                        filename,
                                        result.error_code or "zotero_import_failed",
                                        retryable=result.retryable,
                                    )
                            else:
                                stats["imported"] += 1
                    if job:
                        job.update(
                            "importing_zotero",
                            current=index + 1,
                            total=len(attachments),
                            checkpoint={"attachment_key": attachment_key},
                        )
                self._store_annotations(source_id, annotations, attachment_documents)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise ZoteroImportError(
                "Zotero's local API is unavailable. Enable it in Zotero Settings → Advanced.",
                code="zotero_unavailable",
                retryable=True,
            ) from exc
        self.db.execute(
            """
            UPDATE import_sources SET last_cursor = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(max((int(item.get("version") or 0) for item in items), default=0)), source_id),
        )
        return stats

    async def handle_job(self, context: JobContext, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.sync(
            base_url=payload.get("base_url") or "http://127.0.0.1:23119/api", job=context
        )

    @staticmethod
    async def _fetch_all(
        client: httpx.AsyncClient,
        endpoint: str,
        *,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        start = 0
        while True:
            response = await client.get(
                endpoint,
                params={"start": start, "limit": page_size, "format": "json"},
            )
            if response.status_code != 200:
                raise ZoteroImportError(
                    f"Zotero local API returned HTTP {response.status_code}.",
                    code="zotero_api_error",
                    retryable=response.status_code >= 500,
                )
            page = response.json()
            if not isinstance(page, list):
                raise ZoteroImportError(
                    "Zotero returned an unexpected response.",
                    code="zotero_invalid_response",
                )
            output.extend(page)
            total = int(response.headers.get("Total-Results", len(output)))
            if not page or len(output) >= total or len(page) < page_size:
                return output
            start += len(page)

    async def _download_and_ingest(
        self,
        client: httpx.AsyncClient,
        attachment: dict[str, Any],
        parent: dict[str, Any],
    ) -> tuple[IngestResult, str]:
        attachment_key = str(attachment.get("key", ""))
        data = attachment.get("data", {})
        filename = safe_filename(
            str(data.get("filename") or data.get("title") or f"{attachment_key}.pdf")
        )
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        size_limit = self.ingestion.settings.max_upload_mb * 1024 * 1024
        with tempfile.TemporaryDirectory(dir=self.ingestion.settings.temp_dir) as directory:
            path = Path(directory) / filename
            async with client.stream("GET", f"users/0/items/{attachment_key}/file") as response:
                if response.status_code != 200:
                    raise ZoteroImportError(
                        "A Zotero PDF attachment could not be read.",
                        code="zotero_attachment_unavailable",
                        retryable=response.status_code >= 500,
                    )
                declared_size = int(response.headers.get("Content-Length") or 0)
                if declared_size > size_limit:
                    raise ZoteroImportError(
                        "A Zotero attachment exceeds the configured PDF size limit.",
                        code="file_too_large",
                    )
                received = 0
                with path.open("xb") as handle:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        received += len(chunk)
                        if received > size_limit:
                            raise ZoteroImportError(
                                "A Zotero attachment exceeds the configured PDF size limit.",
                                code="file_too_large",
                            )
                        handle.write(chunk)
            with path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise ZoteroImportError(
                        "The Zotero attachment is not a PDF document.",
                        code="invalid_pdf",
                    )
            parent_data = parent.get("data", {}) if parent else {}
            digest = sha256_file(path)
            result = await self.ingestion.ingest_path(
                path,
                source_kind="zotero",
                metadata_override=self._metadata(parent_data),
                external_version=int(attachment.get("version") or 0),
            )
            return result, digest

    @staticmethod
    def _metadata(data: dict[str, Any]) -> dict[str, Any]:
        creators: list[str] = []
        for creator in data.get("creators") or []:
            name = compact_whitespace(
                creator.get("name")
                or f"{creator.get('firstName', '')} {creator.get('lastName', '')}"
            )
            if name:
                creators.append(name)
        date = str(data.get("date") or "")
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", date)
        extra = str(data.get("extra") or "")
        pmid_match = re.search(r"\bPMID\s*:\s*(\d{6,9})\b", extra, re.IGNORECASE)
        item_type = str(data.get("itemType") or "")
        source_type = {
            "journalArticle": "journal_article",
            "case": "case_report",
            "report": "report",
            "conferencePaper": "conference_paper",
            "preprint": "preprint",
        }.get(item_type, "journal_article")
        return {
            "title": compact_whitespace(data.get("title", "")),
            "authors": ", ".join(creators),
            "journal": compact_whitespace(
                data.get("publicationTitle")
                or data.get("proceedingsTitle")
                or data.get("publisher")
                or ""
            ),
            "publication_year": int(year_match.group(1)) if year_match else None,
            "doi": compact_whitespace(data.get("DOI", "")).lower(),
            "pmid": pmid_match.group(1) if pmid_match else "",
            "abstract": compact_whitespace(data.get("abstractNote", "")),
            "source_type": source_type,
            "metadata_status": "zotero",
        }

    def _ensure_source(self, base_url: str) -> str:
        row = self.db.fetch_one(
            "SELECT id FROM import_sources WHERE kind = 'zotero' AND uri = ?",
            (base_url,),
        )
        if row:
            return str(row["id"])
        source_id = str(uuid.uuid4())
        self.db.execute(
            """
            INSERT INTO import_sources(id, kind, uri, config_json)
            VALUES (?, 'zotero', ?, '{"mode":"read-only-local-api"}')
            """,
            (source_id, base_url),
        )
        return source_id

    def _store_collections(
        self,
        source_id: str,
        collections: list[dict[str, Any]],
        parents: dict[str, dict[str, Any]],
    ) -> None:
        with self.db.transaction() as connection:
            for collection in collections:
                data = collection.get("data", {})
                connection.execute(
                    """
                    INSERT INTO external_collections(
                        source_id, external_key, name, parent_key,
                        external_version, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, external_key) DO UPDATE SET
                        name = excluded.name,
                        parent_key = excluded.parent_key,
                        external_version = excluded.external_version,
                        payload_json = excluded.payload_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        source_id,
                        collection.get("key", ""),
                        data.get("name", "Untitled Zotero collection"),
                        data.get("parentCollection") or "",
                        int(collection.get("version") or 0),
                        json.dumps(collection, separators=(",", ":")),
                    ),
                )
            connection.execute(
                "DELETE FROM external_item_collections WHERE source_id = ?",
                (source_id,),
            )
            for item_key, item in parents.items():
                for collection_key in item.get("data", {}).get("collections") or []:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO external_item_collections(
                            source_id, item_key, collection_key
                        ) VALUES (?, ?, ?)
                        """,
                        (source_id, item_key, collection_key),
                    )

    def _store_external_item(
        self,
        source_id: str,
        item: dict[str, Any],
        document_id: int,
    ) -> None:
        payload = json.dumps(item, sort_keys=True, separators=(",", ":"))
        self.db.execute(
            """
            INSERT INTO external_items(
                source_id, external_key, external_version, document_id, payload_hash
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_id, external_key) DO UPDATE SET
                external_version = excluded.external_version,
                document_id = excluded.document_id,
                payload_hash = excluded.payload_hash,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                source_id,
                item.get("key", ""),
                int(item.get("version") or 0),
                document_id,
                hashlib.sha256(payload.encode()).hexdigest(),
            ),
        )

    def _store_external_attachment(
        self,
        source_id: str,
        attachment: dict[str, Any],
        parent_item_key: str,
        document_id: int,
        digest: str,
    ) -> None:
        file_row = self.db.fetch_one(
            """
            SELECT id FROM document_files
            WHERE document_id = ? AND sha256 = ?
            """,
            (document_id, digest),
        )
        self.db.execute(
            """
            INSERT INTO external_attachments(
                source_id, external_key, parent_item_key, document_id,
                file_id, external_version, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, external_key) DO UPDATE SET
                parent_item_key = excluded.parent_item_key,
                document_id = excluded.document_id,
                file_id = excluded.file_id,
                external_version = excluded.external_version,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                source_id,
                str(attachment.get("key") or ""),
                parent_item_key,
                document_id,
                int(file_row["id"]) if file_row else None,
                int(attachment.get("version") or 0),
                json.dumps(attachment, separators=(",", ":")),
            ),
        )

    def _store_annotations(
        self,
        source_id: str,
        annotations: list[dict[str, Any]],
        attachment_documents: dict[str, int],
    ) -> None:
        with self.db.transaction() as connection:
            for annotation in annotations:
                data = annotation.get("data", {})
                parent_key = str(data.get("parentItem") or "")
                connection.execute(
                    """
                    INSERT INTO external_annotations(
                        source_id, external_key, parent_attachment_key, document_id,
                        external_version, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, external_key) DO UPDATE SET
                        parent_attachment_key = excluded.parent_attachment_key,
                        document_id = excluded.document_id,
                        external_version = excluded.external_version,
                        payload_json = excluded.payload_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        source_id,
                        annotation.get("key", ""),
                        parent_key,
                        attachment_documents.get(parent_key),
                        int(annotation.get("version") or 0),
                        json.dumps(annotation, separators=(",", ":")),
                    ),
                )
