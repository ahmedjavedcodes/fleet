from collections.abc import Generator
from concurrent.futures import Executor, Future

import pytest
from sqlalchemy.orm import Session

from app.services.vector_jobs import VectorJobRunner, set_vector_runner
from app.services.vector_store import get_vector_store, set_vector_store
from tests.fake_vector_store import FakeVectorStore


class InlineExecutor(Executor):
    """Runs background vector jobs immediately, so tests observe their effect."""

    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            future.set_exception(exc)
        return future


class _NoClose:
    """The runner closes the session it opens for DLQ writes; in tests that
    session is the shared, rolled-back-at-the-end test session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._session, name)


@pytest.fixture()
def vectors(db_session: Session) -> Generator[FakeVectorStore, None, None]:
    """Opt-in vector store: an in-memory Pinecone stand-in behind the real
    OrgScopeGuard, with background jobs run inline and retries not sleeping."""
    fake = FakeVectorStore()
    set_vector_store(fake)
    runner = VectorJobRunner(
        store_provider=get_vector_store,
        session_factory=lambda: _NoClose(db_session),
        executor=InlineExecutor(),
        sleep=lambda seconds: runner_sleeps.append(seconds),
    )
    runner_sleeps: list[float] = []
    runner.sleeps = runner_sleeps  # type: ignore[attr-defined]
    set_vector_runner(runner)
    fake.runner = runner  # type: ignore[attr-defined]
    yield fake
