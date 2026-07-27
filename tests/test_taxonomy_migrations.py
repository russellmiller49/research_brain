from __future__ import annotations

import contextlib
import sqlite3

import pytest

import research_memory.migrations as migration_module
from research_memory.db import Database
from research_memory.migrations import MIGRATIONS, Migration, MigrationRunner


def _build_v7_database(path):
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for migration in MIGRATIONS[:7]:
            connection.execute("BEGIN IMMEDIATE")
            migration.apply(connection)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
        connection.execute(
            "INSERT INTO documents(title, normalized_title) VALUES (?, ?)",
            ("Preserved v7 article", "preserved v7 article"),
        )
        connection.commit()


def test_migration_008_is_additive_idempotent_and_snapshotted(tmp_path):
    database_path = tmp_path / "v7.sqlite3"
    backup_dir = tmp_path / "backups"
    _build_v7_database(database_path)
    db = Database(database_path, backup_dir)
    assert db.initialize() == [8]
    assert db.initialize() == []
    assert db.schema_version == 8
    assert (
        db.scalar(
            "SELECT title FROM documents WHERE normalized_title = ?", ("preserved v7 article",)
        )
        == "Preserved v7 article"
    )
    expected_tables = {
        "taxonomy_catalog_versions",
        "taxonomy_nodes",
        "taxonomy_synonyms",
        "taxonomy_edges",
        "specialty_packs",
        "specialty_pack_memberships",
        "research_profile",
        "research_profile_selections",
        "research_profile_preferences",
        "user_navigation_overrides",
        "article_taxonomy_assignments",
        "article_taxonomy_evidence",
        "taxonomy_decision_history",
    }
    actual_tables = {
        str(row["name"])
        for row in db.fetch_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert expected_tables <= actual_tables
    snapshots = list(backup_dir.glob("pre-migration-v7-to-v8-*.sqlite3"))
    assert len(snapshots) == 1
    with contextlib.closing(sqlite3.connect(snapshots[0])) as snapshot:
        assert snapshot.execute("PRAGMA user_version").fetchone()[0] == 7
        assert (
            snapshot.execute(
                "SELECT COUNT(*) FROM documents WHERE normalized_title = ?",
                ("preserved v7 article",),
            ).fetchone()[0]
            == 1
        )
        assert (
            snapshot.execute(
                """
                SELECT COUNT(*) FROM sqlite_master
                WHERE type = 'table' AND name = 'taxonomy_nodes'
                """
            ).fetchone()[0]
            == 0
        )


def test_failed_numbered_migration_rolls_back_its_transaction(tmp_path, monkeypatch):
    database_path = tmp_path / "failure.sqlite3"

    def fail(connection):
        connection.execute("CREATE TABLE should_roll_back(id INTEGER)")
        raise RuntimeError("planned failure")

    monkeypatch.setattr(
        migration_module,
        "MIGRATIONS",
        (Migration(99, "planned-failure", fail),),
    )
    connection = sqlite3.connect(database_path)
    try:
        with pytest.raises(RuntimeError, match="planned failure"):
            MigrationRunner(database_path, tmp_path / "backups").run(connection)
        assert (
            connection.execute(
                """
                SELECT COUNT(*) FROM sqlite_master
                WHERE type = 'table' AND name = 'should_roll_back'
                """
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
    finally:
        connection.close()
