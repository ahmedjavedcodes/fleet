"""Monthly agent-memory maintenance (Pinecone_Migration_Hardened.md §2).

    python -m app.jobs.memory_maintenance            # from backend/

For every organization: dedupe near-identical facts (>= 0.98 cosine, newest
kept), then hard-purge vectors soft-deleted more than 90 days ago. No
scheduler exists in this project -- run this on the 1st of each month from
cron (`0 3 1 * *`) or Windows Task Scheduler. Vector writes it triggers go
through the normal retry/DLQ runner, so the process waits for them to drain
before exiting.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.organization import Organization
from app.services import memory_service
from app.services.vector_jobs import get_vector_runner
from app.services.vector_store import get_vector_store

logger = logging.getLogger("fleet.memory_maintenance")


def run() -> dict[str, int]:
    if get_vector_store() is None:
        logger.warning("PINECONE_API_KEY not configured -- nothing to maintain")
        return {"organizations": 0, "deduplicated": 0}

    totals = {"organizations": 0, "deduplicated": 0}
    with SessionLocal() as db:
        for org_id in db.execute(select(Organization.id)).scalars().all():
            try:
                duplicates = memory_service.dedupe_memories(db, org_id)
                memory_service.prune_inactive_vectors(db, org_id)
            except Exception:  # noqa: BLE001 -- one org's failure must not stop the others
                db.rollback()
                logger.exception("memory maintenance failed for organization %s", org_id)
                continue
            totals["organizations"] += 1
            totals["deduplicated"] += len(duplicates)
            logger.info("org %s: %d duplicate(s) deactivated, prune scheduled", org_id, len(duplicates))

    get_vector_runner().executor.shutdown(wait=True)
    return totals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(run())
