"""Shared fixtures for PostgreSQL-based integration tests.

Provides a session-scoped testcontainers PostgreSQL container,
per-test table cleanup, and helpers for wiring the FastAPI app
to the test database with auth enabled.
"""

import shutil
import subprocess
from collections.abc import AsyncGenerator

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yaai.server.auth.config import (
    APIKeyServiceConfig,
    AuthConfig,
    JWTConfig,
    LocalAuthConfig,
    ServiceAccountsConfig,
)
from yaai.server.auth.dependencies import (
    get_current_identity,
    require_auth,
    require_model_write,
    require_owner,
    set_auth_config,
)
from yaai.server.auth.jwt import create_access_token
from yaai.server.auth.passwords import hash_password
from yaai.server.database import Base, get_db

# Import all models so Base.metadata includes every table
from yaai.server.models import auth as _auth_models  # noqa: F401
from yaai.server.models import inference as _inference_models  # noqa: F401
from yaai.server.models import job as _job_models  # noqa: F401
from yaai.server.models import model as _model_models  # noqa: F401
from yaai.server.models.auth import AuthProvider, User, UserRole

AUTH_CONFIG = AuthConfig(
    enabled=True,
    jwt=JWTConfig(
        secret=SecretStr("integration-test-jwt-secret-32chars!"),
        algorithm="HS256",
        access_token_expire_minutes=60,
        refresh_token_expire_days=30,
    ),
    local=LocalAuthConfig(enabled=True, allow_registration=False),
    service_accounts=ServiceAccountsConfig(
        api_keys=APIKeyServiceConfig(enabled=True),
    ),
)


def _pg_available() -> bool:
    """Check if Docker is available for testcontainers."""
    docker_path = shutil.which("docker")
    if not docker_path:
        return False
    try:
        subprocess.run([docker_path, "info"], capture_output=True, timeout=5, check=True)  # noqa: S603
        return True
    except Exception:
        return False


PG_AVAILABLE = _pg_available()


@pytest.fixture(scope="session")
def pg_container():
    """Start a PostgreSQL container once for the entire test session."""
    if not PG_AVAILABLE:
        pytest.skip("Docker not available")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def pg_url(pg_container) -> str:
    """Construct asyncpg connection URL from container."""
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    user = pg_container.username
    password = pg_container.password
    dbname = pg_container.dbname
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture(scope="session")
def pg_sync_url(pg_container) -> str:
    """Construct psycopg2 connection URL for synchronous operations."""
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    user = pg_container.username
    password = pg_container.password
    dbname = pg_container.dbname
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


@pytest.fixture(scope="session")
def pg_sync_engine(pg_sync_url):
    """Session-scoped sync engine for DDL and cleanup operations."""
    engine = create_engine(pg_sync_url, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def pg_engine(pg_url):
    """Create a session-scoped async engine."""
    return create_async_engine(pg_url, echo=False)


@pytest.fixture(scope="session")
def pg_session_factory(pg_engine):
    """Create a session-scoped session factory."""
    return async_sessionmaker(pg_engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def _create_tables(pg_sync_engine):
    """Create all tables once at session start using a synchronous engine."""
    Base.metadata.create_all(pg_sync_engine)
    yield
    Base.metadata.drop_all(pg_sync_engine)


def _truncate_all_tables(sync_engine):
    """Truncate all tables using a synchronous connection."""
    table_names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    if table_names:
        with sync_engine.connect() as conn:
            conn.execute(text(f"TRUNCATE {table_names} CASCADE"))
            conn.commit()


@pytest.fixture
async def pg_db(pg_session_factory, pg_sync_engine, pg_engine, _create_tables) -> AsyncGenerator[AsyncSession, None]:
    """Yield a per-test async session for seeding data.

    After the test, disposes the async engine pool (to release any
    connections held by the app), then truncates all tables using
    the sync engine for isolation.
    """
    async with pg_session_factory() as session:
        yield session

    # Dispose the async engine pool to release connections from the app
    await pg_engine.dispose()

    # Cleanup: truncate all tables using sync engine (avoids async pool conflicts)
    from yaai.server.auth.service_auth import _token_cache

    _token_cache.clear()
    _truncate_all_tables(pg_sync_engine)


def make_pg_app(session_factory: async_sessionmaker, auth_config: AuthConfig):
    """Wire the FastAPI app to use PG sessions and given auth config.

    Uses the session factory to create fresh sessions per request,
    avoiding asyncpg connection contention. Removes all auth dependency
    overrides so the real auth stack runs. Disables rate limiting.
    """
    from yaai.server.main import app
    from yaai.server.rate_limit import limiter

    limiter.enabled = False
    set_auth_config(auth_config)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Remove any auth overrides so real auth stack runs
    for dep in (get_current_identity, require_auth, require_owner, require_model_write):
        app.dependency_overrides.pop(dep, None)

    return app


# Convenience fixtures for auth-separation tests


@pytest.fixture
async def seeded_owner(pg_db: AsyncSession) -> User:
    """Seed an owner user into the PG database."""
    user = User(
        username="pg-owner",
        email="pg-owner@example.com",
        hashed_password=hash_password("owner-pass-123"),
        role=UserRole.OWNER,
        auth_provider=AuthProvider.LOCAL,
        is_active=True,
    )
    pg_db.add(user)
    await pg_db.commit()
    await pg_db.refresh(user)
    return user


@pytest.fixture
async def seeded_viewer(pg_db: AsyncSession) -> User:
    """Seed a viewer user into the PG database."""
    user = User(
        username="pg-viewer",
        email="pg-viewer@example.com",
        hashed_password=hash_password("viewer-pass-123"),
        role=UserRole.VIEWER,
        auth_provider=AuthProvider.LOCAL,
        is_active=True,
    )
    pg_db.add(user)
    await pg_db.commit()
    await pg_db.refresh(user)
    return user


@pytest.fixture
async def owner_client(
    pg_session_factory: async_sessionmaker, pg_db: AsyncSession, seeded_owner: User
) -> AsyncGenerator:
    """Client authenticated as owner via JWT."""
    from httpx import ASGITransport, AsyncClient

    app = make_pg_app(pg_session_factory, AUTH_CONFIG)
    token = create_access_token(AUTH_CONFIG, str(seeded_owner.id), "owner")
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def viewer_client(
    pg_session_factory: async_sessionmaker, pg_db: AsyncSession, seeded_viewer: User
) -> AsyncGenerator:
    """Client authenticated as viewer via JWT."""
    from httpx import ASGITransport, AsyncClient

    app = make_pg_app(pg_session_factory, AUTH_CONFIG)
    token = create_access_token(AUTH_CONFIG, str(seeded_viewer.id), "viewer")
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def unauth_client(pg_session_factory: async_sessionmaker, pg_db: AsyncSession) -> AsyncGenerator:
    """Client with no authentication."""
    from httpx import ASGITransport, AsyncClient

    app = make_pg_app(pg_session_factory, AUTH_CONFIG)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
