from __future__ import annotations

import json
import os
import platform
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from research_memory.config import Settings
from research_memory.db import Database
from research_memory.utils import resolve_external_destination


class SupportBundleService:
    """Exports diagnostics without content, names, paths, notes, or queries."""

    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings

    def create(self, destination: Path) -> Path:
        destination = resolve_external_destination(destination, self.settings.data_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        database_integrity = self.db.scalar("PRAGMA integrity_check")
        report = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "application": {
                "version": "0.2.0",
                "schema_version": self.db.schema_version,
                "platform": platform.system(),
                "platform_release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            },
            "configuration": {
                "embedding_backend": self.settings.embedding_backend,
                "embedding_index_version": self.settings.embedding_index_version,
                "ocr_available": bool(self.settings.resolved_tesseract_path),
                "network_metadata_enabled": self.settings.enable_network_metadata,
                "diagnostics_enabled": self.settings.diagnostics_enabled,
            },
            "database": {
                "integrity": database_integrity,
                "active_articles": int(
                    self.db.scalar("SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL") or 0
                ),
                "trashed_articles": int(
                    self.db.scalar("SELECT COUNT(*) FROM documents WHERE deleted_at IS NOT NULL")
                    or 0
                ),
                "assets": int(self.db.scalar("SELECT COUNT(*) FROM document_files") or 0),
                "annotations": int(
                    self.db.scalar("SELECT COUNT(*) FROM annotations WHERE deleted_at IS NULL") or 0
                ),
                "jobs_by_state": [
                    dict(row)
                    for row in self.db.fetch_all(
                        """
                        SELECT status, COUNT(*) AS count
                        FROM jobs GROUP BY status ORDER BY status
                        """
                    )
                ],
                "articles_by_extraction_state": [
                    dict(row)
                    for row in self.db.fetch_all(
                        """
                        SELECT extraction_status AS status, COUNT(*) AS count
                        FROM documents
                        WHERE deleted_at IS NULL
                        GROUP BY extraction_status ORDER BY extraction_status
                        """
                    )
                ],
            },
            "recent_jobs": [
                {
                    "type": row["type"],
                    "stage": row["stage"],
                    "status": row["status"],
                    "progress_current": row["progress_current"],
                    "progress_total": row["progress_total"],
                    "error_code": row["error_code"],
                    "retryable": bool(row["retryable"]),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in self.db.fetch_all(
                    """
                    SELECT type, stage, status, progress_current, progress_total,
                           error_code, retryable, created_at, updated_at
                    FROM jobs ORDER BY created_at DESC LIMIT 100
                    """
                )
            ],
            "migrations": [
                dict(row)
                for row in self.db.fetch_all(
                    "SELECT version, name, applied_at FROM schema_migrations ORDER BY version"
                )
            ],
            "redaction": {
                "excluded": [
                    "PDF text",
                    "file names",
                    "file paths",
                    "search queries",
                    "notes",
                    "annotations",
                    "titles",
                    "authors",
                    "job inputs and outputs",
                    "error messages",
                ]
            },
        }
        with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as temporary:
            archive = Path(temporary) / "support.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("support.json", json.dumps(report, indent=2))
            temporary_destination = destination.with_suffix(destination.suffix + ".tmp")
            temporary_destination.write_bytes(archive.read_bytes())
            os.chmod(temporary_destination, 0o600)
            os.replace(temporary_destination, destination)
        return destination
