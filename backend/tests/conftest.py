import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models  # noqa: F401 -- registers all models on Base.metadata
from app.core.database import Base, get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.enums import UserRole
from app.models.organization import Organization
from app.models.user import User

# Dedicated test database -- never the dev 'fleet' database a developer might be
# inspecting in pgAdmin4. Created once via `CREATE DATABASE fleet_test OWNER fleet;`.
TEST_DATABASE_URL = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet_test"

engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    """Wraps each test in an outer transaction + SAVEPOINT so that even though
    service-layer code calls session.commit() internally, nothing survives past
    the test -- the outer connection-level transaction is rolled back at the end."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def organization(db_session: Session) -> Organization:
    org = Organization(id=uuid.uuid4(), name="Test Fleet Co", slug=f"org-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


def make_user(
    db_session: Session,
    org: Organization,
    role: UserRole,
    *,
    email: str | None = None,
    password: str = "password123",
    full_name: str = "Test User",
    is_active: bool = True,
) -> User:
    """Creates a User of any role directly via the DB session. There is no public
    API for this in Plan 00 (register only creates the bootstrap admin) -- direct
    DB insertion is the correct approach for test fixtures, not a workaround."""
    user = User(
        id=uuid.uuid4(),
        organization_id=org.id,
        email=email or f"{role.value}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password(password),
        full_name=full_name,
        role=role,
        is_active=is_active,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, organization_id=user.organization_id, role=user.role)
    return {"Authorization": f"Bearer {token}"}
