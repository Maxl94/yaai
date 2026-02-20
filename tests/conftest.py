from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yaai.server.auth.config import (
    APIKeyServiceConfig,
    AuthConfig,
    GoogleOAuthConfig,
    GoogleSAConfig,
    JWTConfig,
    LocalAuthConfig,
)
from yaai.server.auth.dependencies import (
    CurrentIdentity,
    get_current_identity,
    require_auth,
    require_model_write,
    require_owner,
    set_auth_config,
)
from yaai.server.database import Base, get_db
from yaai.server.models import auth as _auth_models  # noqa: F401
from yaai.server.models import inference as _inference_models  # noqa: F401
from yaai.server.models import job as _job_models  # noqa: F401
from yaai.server.models import model as _model_models  # noqa: F401
from yaai.server.models.auth import UserRole

# Prevent all auth BaseSettings classes from reading .env during tests.
# This ensures tests are deterministic regardless of what's in the developer's .env file.
# Tests that need specific env values use monkeypatch.setenv() which sets os.environ directly.
for _cls in (JWTConfig, LocalAuthConfig, GoogleOAuthConfig, GoogleSAConfig, APIKeyServiceConfig, AuthConfig):
    _cls.model_config["env_file"] = None

TEST_DATABASE_URL = "sqlite+aiosqlite://"

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    from yaai.server.main import app
    from yaai.server.rate_limit import limiter

    # Disable rate limiting in tests
    limiter.enabled = False

    async def override_get_db():
        yield db_session

    # Disable auth for tests — all requests act as owner
    test_owner = CurrentIdentity(
        user_id="00000000-0000-0000-0000-000000000000",
        role=UserRole.OWNER,
        identity_type="test",
        username="test-owner",
    )
    set_auth_config(AuthConfig(enabled=False))

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_identity] = lambda: test_owner
    app.dependency_overrides[require_auth] = lambda: test_owner
    app.dependency_overrides[require_owner] = lambda: test_owner
    app.dependency_overrides[require_model_write] = lambda: test_owner

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# --- Reusable helpers ---


async def create_model(client: AsyncClient, name: str = "test-model") -> dict:
    resp = await client.post("/api/v1/models", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["data"]


async def create_version(client: AsyncClient, model_id: str) -> dict:
    resp = await client.post(
        f"/api/v1/models/{model_id}/versions",
        json={
            "version": "v1.0",
            "schema": [
                {"direction": "input", "field_name": "age", "data_type": "numerical"},
                {"direction": "input", "field_name": "gender", "data_type": "categorical"},
                {"direction": "output", "field_name": "score", "data_type": "numerical"},
            ],
        },
    )
    assert resp.status_code == 201
    return resp.json()["data"]
