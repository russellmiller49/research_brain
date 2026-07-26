from __future__ import annotations

import asyncio
import json
import sys
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from research_memory.contracts import ImportIssue, ImportJob
from research_memory.db import Database

JobHandler = Callable[["JobContext", dict[str, Any]], Awaitable[dict[str, Any]]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class JobCanceled(RuntimeError):
    pass


class JobsBusy(RuntimeError):
    pass


class JobStore:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        job_type: str,
        source: str,
        payload: dict[str, Any],
        *,
        progress_total: int = 0,
    ) -> str:
        job_id = str(uuid.uuid4())
        self.db.execute(
            """
            INSERT INTO jobs(
                id, type, source, input_json, progress_total, status, stage
            ) VALUES (?, ?, ?, ?, ?, 'queued', 'queued')
            """,
            (job_id, job_type, source, json.dumps(payload), progress_total),
        )
        return job_id

    def recover_interrupted(self) -> int:
        cursor = self.db.execute(
            """
            UPDATE jobs
            SET status = 'queued', stage = 'resuming', retryable = 1,
                updated_at = ?, error_code = NULL, error_message = NULL
            WHERE status = 'running'
            """,
            (_utc_now(),),
        )
        return cursor.rowcount

    def reconcile_duplicate_import_failures(self) -> int:
        """Repair false failures caused by a concurrent import winning the SHA race."""

        rows = self.db.fetch_all(
            """
            SELECT j.id, f.document_id, f.file_name
            FROM jobs j
            JOIN document_files f
              ON f.original_path = json_extract(j.input_json, '$.path')
            JOIN documents d ON d.id = f.document_id
            WHERE j.type = 'import'
              AND j.status = 'failed'
              AND j.error_code = 'integrityerror'
              AND j.error_message LIKE
                  'UNIQUE constraint failed: document_files.sha256%'
              AND f.availability = 'available'
              AND d.deleted_at IS NULL
            ORDER BY j.created_at
            """
        )
        for row in rows:
            result = {
                "status": "duplicate",
                "document_id": int(row["document_id"]),
                "file_name": row["file_name"],
                "message": "Exact bytes already exist; the existing article was reused.",
                "error_code": None,
                "retryable": False,
                "review_state": "ready",
            }
            self.succeeded(str(row["id"]), {"results": [result]})
        return len(rows)

    def get(self, job_id: str) -> ImportJob | None:
        row = self.db.fetch_one(
            """
            SELECT j.*, (
                SELECT COUNT(*) FROM job_issues i WHERE i.job_id = j.id
            ) AS issue_count
            FROM jobs j WHERE j.id = ?
            """,
            (job_id,),
        )
        return self._contract(row) if row else None

    def list_jobs(self, *, limit: int = 100) -> list[ImportJob]:
        rows = self.db.fetch_all(
            """
            SELECT j.*, (
                SELECT COUNT(*) FROM job_issues i WHERE i.job_id = j.id
            ) AS issue_count
            FROM jobs j ORDER BY j.created_at DESC LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        )
        return [self._contract(row) for row in rows]

    def record_issue(
        self,
        job_id: str,
        source_label: str,
        error_code: str,
        *,
        retryable: bool,
    ) -> None:
        self.db.execute(
            """
            INSERT OR IGNORE INTO job_issues(
                job_id, source_label, error_code, retryable
            ) VALUES (?, ?, ?, ?)
            """,
            (job_id, source_label[:500], error_code[:200], int(retryable)),
        )

    def issues(self, job_id: str) -> list[ImportIssue]:
        rows = self.db.fetch_all(
            "SELECT * FROM job_issues WHERE job_id = ? ORDER BY id",
            (job_id,),
        )
        return [
            ImportIssue(
                id=int(row["id"]),
                job_id=row["job_id"],
                source_label=row["source_label"],
                error_code=row["error_code"],
                retryable=bool(row["retryable"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def queued_ids(self) -> list[str]:
        rows = self.db.fetch_all("SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at")
        return [str(row["id"]) for row in rows]

    def input(self, job_id: str) -> tuple[str, dict[str, Any]]:
        row = self.db.fetch_one("SELECT type, input_json FROM jobs WHERE id = ?", (job_id,))
        if not row:
            raise KeyError(job_id)
        return str(row["type"]), json.loads(row["input_json"] or "{}")

    def checkpoint(self, job_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT checkpoint_json FROM jobs WHERE id = ?", (job_id,))
        if not row:
            raise KeyError(job_id)
        value = json.loads(row["checkpoint_json"] or "{}")
        return value if isinstance(value, dict) else {}

    def mark_running(self, job_id: str) -> None:
        self.db.execute(
            """
            UPDATE jobs
            SET status = 'running', stage = 'starting', attempt = attempt + 1,
                started_at = COALESCE(started_at, ?), updated_at = ?,
                error_code = NULL, error_message = NULL
            WHERE id = ?
            """,
            (_utc_now(), _utc_now(), job_id),
        )

    def progress(
        self,
        job_id: str,
        *,
        stage: str,
        current: int | None = None,
        total: int | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        row = self.db.fetch_one(
            "SELECT progress_current, progress_total, checkpoint_json FROM jobs WHERE id = ?",
            (job_id,),
        )
        if not row:
            raise KeyError(job_id)
        self.db.execute(
            """
            UPDATE jobs
            SET stage = ?, progress_current = ?, progress_total = ?,
                checkpoint_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                stage,
                int(row["progress_current"]) if current is None else current,
                int(row["progress_total"]) if total is None else total,
                row["checkpoint_json"]
                if checkpoint is None
                else json.dumps(checkpoint, separators=(",", ":")),
                _utc_now(),
                job_id,
            ),
        )

    def succeeded(self, job_id: str, output: dict[str, Any]) -> None:
        self.db.execute(
            """
            UPDATE jobs
            SET status = 'succeeded', stage = 'complete', output_json = ?,
                progress_current = CASE
                    WHEN progress_total > 0 THEN progress_total
                    ELSE progress_current
                END,
                error_code = NULL, error_message = NULL, retryable = 0,
                cancel_requested = 0, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(output), _utc_now(), _utc_now(), job_id),
        )

    def failed(
        self,
        job_id: str,
        *,
        error_code: str,
        message: str,
        retryable: bool,
    ) -> None:
        self.db.execute(
            """
            UPDATE jobs
            SET status = 'failed', stage = 'failed', error_code = ?,
                error_message = ?, retryable = ?, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                error_code,
                message[:2_000],
                int(retryable),
                _utc_now(),
                _utc_now(),
                job_id,
            ),
        )

    def request_cancel(self, job_id: str) -> None:
        self.db.execute(
            """
            UPDATE jobs SET cancel_requested = 1, updated_at = ?
            WHERE id = ? AND status IN ('queued', 'running', 'paused')
            """,
            (_utc_now(), job_id),
        )

    def canceled(self, job_id: str) -> None:
        self.db.execute(
            """
            UPDATE jobs
            SET status = 'canceled', stage = 'canceled', finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (_utc_now(), _utc_now(), job_id),
        )

    def retry(self, job_id: str) -> bool:
        cursor = self.db.execute(
            """
            UPDATE jobs
            SET status = 'queued', stage = 'queued', cancel_requested = 0,
                error_code = NULL, error_message = NULL, finished_at = NULL,
                updated_at = ?
            WHERE id = ? AND status IN ('failed', 'canceled') AND retryable = 1
            """,
            (_utc_now(), job_id),
        )
        return cursor.rowcount == 1

    def cancellation_requested(self, job_id: str) -> bool:
        return bool(self.db.scalar("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)))

    @staticmethod
    def _contract(row: Any) -> ImportJob:
        total = int(row["progress_total"] or 0)
        current = int(row["progress_current"] or 0)
        progress = min(1.0, current / total) if total else 0.0
        return ImportJob(
            id=row["id"],
            type=row["type"],
            source=row["source"],
            stage=row["stage"],
            status=row["status"],
            progress_current=current,
            progress_total=total,
            progress=progress,
            retryable=bool(row["retryable"]),
            error_code=row["error_code"],
            issue_count=int(row["issue_count"] if "issue_count" in row.keys() else 0),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class JobContext:
    def __init__(self, job_id: str, store: JobStore):
        self.job_id = job_id
        self.store = store

    def update(
        self,
        stage: str,
        *,
        current: int | None = None,
        total: int | None = None,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        self.raise_if_canceled()
        self.store.progress(
            self.job_id,
            stage=stage,
            current=current,
            total=total,
            checkpoint=checkpoint,
        )

    def raise_if_canceled(self) -> None:
        if self.store.cancellation_requested(self.job_id):
            raise JobCanceled("The job was canceled")


class BackgroundJobManager:
    def __init__(self, store: JobStore, worker_count: int = 2):
        self.store = store
        self.worker_count = max(1, min(worker_count, 8))
        self.handlers: dict[str, JobHandler] = {}
        self.exclusive_job_types: set[str] = set()
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.tasks: list[asyncio.Task[None]] = []
        self._enqueued: set[str] = set()
        self._sensitive_inputs: dict[str, dict[str, Any]] = {}
        self._accepting_work = True
        self._active = 0
        self._exclusive_active = False
        self._exclusive_waiters = 0
        self._activity = asyncio.Condition()
        self._maintenance = False

    def register(
        self,
        job_type: str,
        handler: JobHandler,
        *,
        exclusive: bool = False,
    ) -> None:
        self.handlers[job_type] = handler
        if exclusive:
            self.exclusive_job_types.add(job_type)

    async def start(self) -> None:
        if self.tasks:
            return
        self.store.recover_interrupted()
        for job_id in self.store.queued_ids():
            self.enqueue(job_id)
        self.tasks = [
            asyncio.create_task(self._worker(index), name=f"research-memory-worker-{index}")
            for index in range(self.worker_count)
        ]

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        self._sensitive_inputs.clear()

    @asynccontextmanager
    async def maintenance(self):
        """Exclude background writers for a short database maintenance operation."""

        async with self._activity:
            self._accepting_work = False
            pending = int(
                self.store.db.scalar(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
                )
                or 0
            )
            if self._active or pending:
                self._accepting_work = True
                self._activity.notify_all()
                raise JobsBusy("Background jobs are active")
            self._maintenance = True
        try:
            yield
        finally:
            async with self._activity:
                self._maintenance = False
                self._accepting_work = True
                self._activity.notify_all()

    @property
    def in_maintenance(self) -> bool:
        return self._maintenance

    def enqueue(
        self,
        job_id: str,
        *,
        sensitive_input: dict[str, Any] | None = None,
    ) -> None:
        if sensitive_input:
            self._sensitive_inputs[job_id] = dict(sensitive_input)
        if job_id in self._enqueued:
            return
        self._enqueued.add(job_id)
        self.queue.put_nowait(job_id)

    async def _worker(self, _worker_index: int) -> None:
        while True:
            job_id = await self.queue.get()
            self._enqueued.discard(job_id)
            active = False
            exclusive = False
            try:
                job_type, _ = self.store.input(job_id)
                exclusive = job_type in self.exclusive_job_types
                async with self._activity:
                    if exclusive:
                        self._exclusive_waiters += 1
                    try:

                        def ready_to_start(exclusive_job: bool = exclusive) -> bool:
                            return self._accepting_work and (
                                self._active == 0
                                if exclusive_job
                                else not self._exclusive_active and self._exclusive_waiters == 0
                            )

                        await self._activity.wait_for(ready_to_start)
                    finally:
                        if exclusive:
                            self._exclusive_waiters -= 1
                    self._active += 1
                    self._exclusive_active = exclusive
                    active = True
                await self._run(job_id)
            finally:
                if active:
                    async with self._activity:
                        self._active -= 1
                        if exclusive:
                            self._exclusive_active = False
                        self._activity.notify_all()
                self.queue.task_done()

    async def _run(self, job_id: str) -> None:
        job_type, payload = self.store.input(job_id)
        payload.update(self._sensitive_inputs.pop(job_id, {}))
        handler = self.handlers.get(job_type)
        if not handler:
            self.store.failed(
                job_id,
                error_code="unsupported_job",
                message=f"No handler is registered for {job_type}",
                retryable=False,
            )
            return
        self.store.mark_running(job_id)
        context = JobContext(job_id, self.store)
        try:
            output = await handler(context, payload)
        except JobCanceled:
            self.store.canceled(job_id)
        except Exception as exc:
            retryable = bool(getattr(exc, "retryable", isinstance(exc, (OSError, TimeoutError))))
            error_code = str(getattr(exc, "code", exc.__class__.__name__.lower()))
            print(f"Research Memory background job failed [{error_code}]", file=sys.stderr)
            self.store.failed(
                job_id,
                error_code=error_code,
                message=str(exc) or exc.__class__.__name__,
                retryable=retryable,
            )
        else:
            self.store.succeeded(job_id, output)
