"""Background vector writes with retry + dead-letter queue
(Pinecone_Migration_Hardened.md §3).

Every Pinecone write is a plain-data job ({"op", "namespace", ...}) rather
than a closure, so a job that lands in failed_vector_jobs can be replayed
verbatim later. Attempts are made at +0s, +1s and +4s; after the third
failure the job is written to Postgres and logged at ERROR (the DLQ alert).
The user's request never waits on any of this.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.memory import FailedVectorJob
from app.services.vector_store import VectorStore

logger = logging.getLogger("fleet.vector_jobs")

RETRY_DELAYS_SECONDS = (0.0, 1.0, 4.0)


def execute_job(store: VectorStore, job: dict[str, Any]) -> None:
    op, namespace = job["op"], job["namespace"]
    if op == "upsert":
        store.upsert(job["vectors"], namespace)
    elif op == "update_metadata":
        store.update_metadata(job["filters"], job["set_metadata"], namespace)
    elif op == "delete":
        store.delete(job["filters"], namespace)
    else:
        raise ValueError(f"unknown vector job op {op!r}")


class VectorJobRunner:
    def __init__(
        self,
        *,
        store_provider: Callable[[], VectorStore | None],
        session_factory: Callable[[], Session],
        executor: Executor | None = None,
        sleep: Callable[[float], None] = time.sleep,
        delays: tuple[float, ...] = RETRY_DELAYS_SECONDS,
    ) -> None:
        self.store_provider = store_provider
        self.session_factory = session_factory
        self.executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="vector-jobs")
        self.sleep = sleep
        self.delays = delays

    def submit(self, organization_id: uuid.UUID | str, job: dict[str, Any]) -> Future | None:
        """Fire-and-forget. None when no vector store is configured."""
        if self.store_provider() is None:
            return None
        return self.executor.submit(self._run, str(organization_id), job)

    def run_sync(self, organization_id: uuid.UUID | str, job: dict[str, Any]) -> bool:
        """Same retry + dead-letter policy, on the caller's thread -- for work
        that is already running in the background (document ingestion)."""
        if self.store_provider() is None:
            return False
        return self._run(str(organization_id), job)

    def _run(self, organization_id: str, job: dict[str, Any]) -> bool:
        last_error: Exception | None = None
        for delay in self.delays:
            if delay:
                self.sleep(delay)
            try:
                execute_job(self.store_provider(), job)
                return True
            except Exception as exc:  # noqa: BLE001 -- every failure mode ends in the DLQ, never the user's turn
                last_error = exc
                logger.warning("vector job %s failed (%s), retrying", job.get("op"), type(exc).__name__)
        self._dead_letter(organization_id, job, last_error)
        return False

    def _dead_letter(self, organization_id: str, job: dict[str, Any], error: Exception | None) -> None:
        message = f"{type(error).__name__}: {error}" if error else "unknown error"
        session = self.session_factory()
        try:
            session.add(
                FailedVectorJob(
                    organization_id=uuid.UUID(organization_id),
                    payload=job,
                    error_message=message[:2_000],
                    attempts=len(self.delays),
                )
            )
            session.commit()
            depth = session.execute(select(func.count()).select_from(FailedVectorJob)).scalar_one()
            logger.error("ALERT: vector job %s dead-lettered after %d attempts (DLQ depth=%d): %s",
                         job.get("op"), len(self.delays), depth, message)
        except Exception:  # noqa: BLE001 -- last resort: never let the DLQ write itself crash the worker
            logger.critical("vector job %s LOST: DLQ write failed. Job: %s", job.get("op"), job, exc_info=True)
        finally:
            session.close()


_runner: VectorJobRunner | None = None


def get_vector_runner() -> VectorJobRunner:
    global _runner
    if _runner is None:
        from app.core.database import SessionLocal
        from app.services.vector_store import get_vector_store

        _runner = VectorJobRunner(store_provider=get_vector_store, session_factory=SessionLocal)
    return _runner


def set_vector_runner(runner: VectorJobRunner | None) -> None:
    global _runner
    _runner = runner
