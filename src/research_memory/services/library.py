from __future__ import annotations

import sqlite3

from research_memory.db import Database
from research_memory.services.assets import AssetIntegrityError, AssetStore


class LibraryService:
    """Recoverable article deletion that never touches an import source."""

    def __init__(self, db: Database, assets: AssetStore | None = None):
        self.db = db
        self.assets = assets

    def move_to_trash(self, document_id: int) -> bool:
        cursor = self.db.execute(
            """
            UPDATE documents
            SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND deleted_at IS NULL
            """,
            (document_id,),
        )
        return cursor.rowcount == 1

    def restore(self, document_id: int) -> bool:
        cursor = self.db.execute(
            """
            UPDATE documents
            SET deleted_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND deleted_at IS NOT NULL
            """,
            (document_id,),
        )
        return cursor.rowcount == 1

    def list_trash(self) -> list[sqlite3.Row]:
        return self.db.fetch_all(
            """
            SELECT d.*, datetime(d.deleted_at, '+30 days') AS purge_after
            FROM documents d
            WHERE d.deleted_at IS NOT NULL
            ORDER BY d.deleted_at DESC
            """
        )

    def purge_expired(self, *, retention_days: int = 30) -> int:
        rows = self.db.fetch_all(
            """
            SELECT d.id, f.object_path, f.sha256
            FROM documents d
            LEFT JOIN document_files f ON f.document_id = d.id
            WHERE d.deleted_at IS NOT NULL
              AND d.deleted_at < datetime('now', ?)
            """,
            (f"-{retention_days} days",),
        )
        document_ids = sorted({int(row["id"]) for row in rows})
        if not document_ids:
            return 0
        managed_objects = {
            (str(row["object_path"]), str(row["sha256"]))
            for row in rows
            if row["object_path"] and row["sha256"]
        }
        with self.db.transaction() as connection:
            placeholders = ",".join("?" for _ in document_ids)
            connection.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", document_ids)
        for object_path, digest in managed_objects:
            still_referenced = self.db.scalar(
                "SELECT COUNT(*) FROM document_files WHERE object_path = ?",
                (object_path,),
            )
            if still_referenced or not self.assets:
                continue
            try:
                path = self.assets.resolve(object_path, digest)
            except (AssetIntegrityError, FileNotFoundError, ValueError):
                continue
            if path.is_file():
                path.unlink()
        return len(document_ids)
