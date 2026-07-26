from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Generator, Iterable
from pathlib import Path
from typing import Any

from research_memory.migrations import CURRENT_SCHEMA_VERSION, MigrationRunner


class Database:
    """SQLite wrapper with explicit transactions and numbered migrations."""

    def __init__(self, path: str | Path, backup_dir: str | Path | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir = Path(backup_dir) if backup_dir else self.path.parent / "backups"

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> list[int]:
        with contextlib.closing(self.connect()) as connection:
            return MigrationRunner(self.path, self.backup_dir).run(connection)

    @property
    def schema_version(self) -> int:
        return int(self.scalar("PRAGMA user_version") or 0)

    @property
    def current_schema_version(self) -> int:
        return CURRENT_SCHEMA_VERSION

    @contextlib.contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def execute(self, query: str, parameters: Iterable[Any] = ()) -> sqlite3.Cursor:
        with contextlib.closing(self.connect()) as connection:
            cursor = connection.execute(query, tuple(parameters))
            connection.commit()
            return cursor

    def execute_many(
        self,
        query: str,
        parameters: Iterable[tuple[Any, ...]],
    ) -> None:
        with contextlib.closing(self.connect()) as connection:
            connection.executemany(query, parameters)
            connection.commit()

    def fetch_one(
        self,
        query: str,
        parameters: Iterable[Any] = (),
    ) -> sqlite3.Row | None:
        with contextlib.closing(self.connect()) as connection:
            return connection.execute(query, tuple(parameters)).fetchone()

    def fetch_all(
        self,
        query: str,
        parameters: Iterable[Any] = (),
    ) -> list[sqlite3.Row]:
        with contextlib.closing(self.connect()) as connection:
            return list(connection.execute(query, tuple(parameters)).fetchall())

    def scalar(self, query: str, parameters: Iterable[Any] = ()) -> Any:
        row = self.fetch_one(query, parameters)
        return None if row is None else row[0]

    def online_backup(self, destination: str | Path) -> Path:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            contextlib.closing(self.connect()) as source,
            contextlib.closing(sqlite3.connect(target)) as backup,
        ):
            source.backup(backup)
        return target
