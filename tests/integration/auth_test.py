"""Integration tests for auth API endpoints.

These tests enable auth and exercise the full auth flow:
login, token refresh, logout, user CRUD, service accounts, and model access.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from yaai.server.auth.config import AuthConfig, GoogleOAuthConfig, JWTConfig, LocalAuthConfig, OAuthConfig
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
from yaai.server.models import auth as _auth_models  # noqa: F401
from yaai.server.models import inference as _inference_models  # noqa: F401
from yaai.server.models import job as _job_models  # noqa: F401
from yaai.server.models import model as _model_models  # noqa: F401
from yaai.server.models.auth import AuthProvider, User, UserRole

TEST_DATABASE_URL = "sqlite+aiosqlite://"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestingSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

AUTH_CONFIG = AuthConfig(
    enabled=True,
    jwt=JWTConfig(
        secret=SecretStr("integration-test-jwt-secret-32chars!"),
    ),
    local=LocalAuthConfig(allow_registration=False),
    oauth=OAuthConfig(google=GoogleOAuthConfig(enabled=False)),
)


@pytest.fixture(autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session():
    async with TestingSessionLocal() as session:
        yield session


@pytest.fixture
async def seeded_owner(db_session: AsyncSession):
    """Create an owner user in the database."""
    user = User(
        username="admin",
        email="admin@example.com",
        hashed_password=hash_password("admin-password-123"),
        role=UserRole.OWNER,
        auth_provider=AuthProvider.LOCAL,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def seeded_viewer(db_session: AsyncSession):
    """Create a viewer user in the database."""
    user = User(
        username="viewer",
        email="viewer@example.com",
        hashed_password=hash_password("viewer-password-123"),
        role=UserRole.VIEWER,
        auth_provider=AuthProvider.LOCAL,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _make_client_no_auth_override(db_session):
    """Create a test client WITHOUT auth overrides — auth is active."""
    from yaai.server.main import app
    from yaai.server.rate_limit import limiter

    limiter.enabled = False
    set_auth_config(AUTH_CONFIG)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # Remove any auth overrides so real auth runs
    app.dependency_overrides.pop(get_current_identity, None)
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_owner, None)
    app.dependency_overrides.pop(require_model_write, None)

    return app


@pytest.fixture
async def auth_client(db_session: AsyncSession):
    """Client with auth enabled — no auth dependency overrides."""
    app = _make_client_no_auth_override(db_session)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def owner_client(db_session: AsyncSession, seeded_owner: User):
    """Client with a valid owner access token in the Authorization header."""
    app = _make_client_no_auth_override(db_session)
    token = create_access_token(AUTH_CONFIG, str(seeded_owner.id), seeded_owner.role.value)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def viewer_client(db_session: AsyncSession, seeded_viewer: User):
    """Client with a valid viewer access token."""
    app = _make_client_no_auth_override(db_session)
    token = create_access_token(AUTH_CONFIG, str(seeded_viewer.id), seeded_viewer.role.value)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


# Auth Config Endpoint


async def test_get_auth_config(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/auth/config")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["enabled"] is True
    assert data["local_enabled"] is True
    assert data["google_oauth_enabled"] is False


# Login


async def test_login_success(auth_client: AsyncClient, seeded_owner: User):
    resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-password-123"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"  # noqa: S105
    assert data["user"]["username"] == "admin"
    assert data["user"]["role"] == "owner"


async def test_login_wrong_password(auth_client: AsyncClient, seeded_owner: User):
    resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_login_unknown_user(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "nonexistent", "password": "any"},
    )
    assert resp.status_code == 401


# Token Refresh


async def test_refresh_token_success(auth_client: AsyncClient, seeded_owner: User):
    # Login first to get tokens
    login_resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-password-123"},
    )
    tokens = login_resp.json()["data"]

    # Refresh
    resp = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert resp.status_code == 200
    new_tokens = resp.json()["data"]
    assert "access_token" in new_tokens
    assert "refresh_token" in new_tokens
    # Old refresh token should be revoked — using it again should fail
    resp2 = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert resp2.status_code == 401


async def test_refresh_with_access_token_fails(auth_client: AsyncClient, seeded_owner: User):
    """Using an access token as a refresh token should fail."""
    token = create_access_token(AUTH_CONFIG, str(seeded_owner.id), "owner")
    resp = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": token},
    )
    assert resp.status_code == 401


async def test_refresh_with_garbage_token_fails(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "not-a-jwt"},
    )
    assert resp.status_code == 401


# Logout


async def test_logout_revokes_refresh_token(auth_client: AsyncClient, seeded_owner: User):
    login_resp = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-password-123"},
    )
    tokens = login_resp.json()["data"]

    # Logout
    resp = await auth_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert resp.status_code == 200

    # Refresh should now fail
    resp2 = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert resp2.status_code == 401


async def test_logout_with_invalid_token_succeeds(auth_client: AsyncClient):
    """Logout with garbage token should still return 200 (already logged out)."""
    resp = await auth_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "garbage"},
    )
    assert resp.status_code == 200


# Get Current User


async def test_get_me(owner_client: AsyncClient, seeded_owner: User):
    resp = await owner_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["username"] == "admin"
    assert data["role"] == "owner"


async def test_get_me_unauthenticated(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# Change Password


async def test_change_password(owner_client: AsyncClient, auth_client: AsyncClient, seeded_owner: User):
    resp = await owner_client.put(
        "/api/v1/auth/me/password",
        json={"current_password": "admin-password-123", "new_password": "new-secure-password"},
    )
    assert resp.status_code == 200

    # Login with new password
    resp2 = await auth_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "new-secure-password"},
    )
    assert resp2.status_code == 200


async def test_change_password_wrong_current(owner_client: AsyncClient):
    resp = await owner_client.put(
        "/api/v1/auth/me/password",
        json={"current_password": "wrong-current", "new_password": "new-password-ok"},
    )
    assert resp.status_code == 400


# User Management (Owner Only)


async def test_list_users(owner_client: AsyncClient, seeded_owner: User):
    resp = await owner_client.get("/api/v1/auth/users")
    assert resp.status_code == 200
    users = resp.json()["data"]
    assert len(users) >= 1
    assert any(u["username"] == "admin" for u in users)


async def test_create_user(owner_client: AsyncClient):
    resp = await owner_client.post(
        "/api/v1/auth/users",
        json={"username": "newuser", "password": "password1234", "role": "viewer"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["username"] == "newuser"
    assert data["role"] == "viewer"


async def test_create_user_duplicate_username(owner_client: AsyncClient, seeded_owner: User):
    resp = await owner_client.post(
        "/api/v1/auth/users",
        json={"username": "admin", "password": "password1234"},
    )
    assert resp.status_code == 409


async def test_create_user_duplicate_email(owner_client: AsyncClient, seeded_owner: User):
    resp = await owner_client.post(
        "/api/v1/auth/users",
        json={
            "username": "another",
            "password": "password1234",
            "email": "admin@example.com",
        },
    )
    assert resp.status_code == 409


async def test_update_user(owner_client: AsyncClient, seeded_owner: User, seeded_viewer: User):
    resp = await owner_client.put(
        f"/api/v1/auth/users/{seeded_viewer.id}",
        json={"role": "owner"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "owner"


async def test_update_user_not_found(owner_client: AsyncClient):
    resp = await owner_client.put(
        f"/api/v1/auth/users/{uuid.uuid4()}",
        json={"role": "viewer"},
    )
    assert resp.status_code == 404


async def test_delete_user(owner_client: AsyncClient, seeded_viewer: User):
    resp = await owner_client.delete(f"/api/v1/auth/users/{seeded_viewer.id}")
    assert resp.status_code == 204


async def test_delete_user_not_found(owner_client: AsyncClient):
    resp = await owner_client.delete(f"/api/v1/auth/users/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_viewer_cannot_list_users(viewer_client: AsyncClient):
    resp = await viewer_client.get("/api/v1/auth/users")
    assert resp.status_code == 403


async def test_viewer_cannot_create_user(viewer_client: AsyncClient):
    resp = await viewer_client.post(
        "/api/v1/auth/users",
        json={"username": "hacker", "password": "password1234"},
    )
    assert resp.status_code == 403


# Service Account Management


async def test_create_service_account(owner_client: AsyncClient):
    resp = await owner_client.post(
        "/api/v1/auth/service-accounts",
        json={"name": "ci-pipeline", "auth_type": "api_key", "description": "CI/CD"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["service_account"]["name"] == "ci-pipeline"
    assert data["raw_key"] is not None
    assert data["raw_key"].startswith("yaam_")


async def test_list_service_accounts(owner_client: AsyncClient):
    # Create one first
    await owner_client.post(
        "/api/v1/auth/service-accounts",
        json={"name": "for-listing", "auth_type": "api_key"},
    )
    resp = await owner_client.get("/api/v1/auth/service-accounts")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) >= 1


async def test_delete_service_account(owner_client: AsyncClient):
    create_resp = await owner_client.post(
        "/api/v1/auth/service-accounts",
        json={"name": "to-delete", "auth_type": "api_key"},
    )
    sa_id = create_resp.json()["data"]["service_account"]["id"]
    resp = await owner_client.delete(f"/api/v1/auth/service-accounts/{sa_id}")
    assert resp.status_code == 204


async def test_delete_service_account_not_found(owner_client: AsyncClient):
    resp = await owner_client.delete(f"/api/v1/auth/service-accounts/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_regenerate_api_key(owner_client: AsyncClient):
    create_resp = await owner_client.post(
        "/api/v1/auth/service-accounts",
        json={"name": "regen-key", "auth_type": "api_key"},
    )
    sa_id = create_resp.json()["data"]["service_account"]["id"]
    old_key = create_resp.json()["data"]["raw_key"]

    resp = await owner_client.post(f"/api/v1/auth/service-accounts/{sa_id}/regenerate-key")
    assert resp.status_code == 200
    new_key = resp.json()["data"]["raw_key"]
    assert new_key != old_key
    assert new_key.startswith("yaam_")


async def test_regenerate_key_not_found(owner_client: AsyncClient):
    resp = await owner_client.post(f"/api/v1/auth/service-accounts/{uuid.uuid4()}/regenerate-key")
    assert resp.status_code == 404


async def test_service_account_api_key_auth(db_session: AsyncSession, seeded_owner: User):
    """An API key created for a SA should work as authentication."""
    from yaai.server.main import app
    from yaai.server.rate_limit import limiter

    limiter.enabled = False
    set_auth_config(AUTH_CONFIG)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_current_identity, None)
    app.dependency_overrides.pop(require_auth, None)
    app.dependency_overrides.pop(require_owner, None)
    app.dependency_overrides.pop(require_model_write, None)

    owner_token = create_access_token(AUTH_CONFIG, str(seeded_owner.id), "owner")
    transport = ASGITransport(app=app, raise_app_exceptions=False)

    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Create SA as owner
        create_resp = await c.post(
            "/api/v1/auth/service-accounts",
            json={"name": "auth-test-sa", "auth_type": "api_key"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert create_resp.status_code == 201
        raw_key = create_resp.json()["data"]["raw_key"]
        sa_id = create_resp.json()["data"]["service_account"]["id"]

        # Create a model as owner, then grant SA access
        model_resp = await c.post(
            "/api/v1/models",
            json={"name": "sa-test-model"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert model_resp.status_code == 201
        model_id = model_resp.json()["data"]["id"]

        grant_resp = await c.post(
            f"/api/v1/auth/models/{model_id}/access",
            json={"service_account_id": sa_id},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert grant_resp.status_code == 201

        # Now use the API key to access the API
        resp = await c.get(
            f"/api/v1/models/{model_id}",
            headers={"X-API-Key": raw_key},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "sa-test-model"

    app.dependency_overrides.clear()


# Model Access Management


async def test_grant_model_access(owner_client: AsyncClient):
    # Create SA
    sa_resp = await owner_client.post(
        "/api/v1/auth/service-accounts",
        json={"name": "access-test", "auth_type": "api_key"},
    )
    sa_id = sa_resp.json()["data"]["service_account"]["id"]

    # We need a model — create one via the override client
    model_resp = await owner_client.post("/api/v1/models", json={"name": "access-model"})
    model_id = model_resp.json()["data"]["id"]

    # Grant access
    resp = await owner_client.post(
        f"/api/v1/auth/models/{model_id}/access",
        json={"service_account_id": sa_id},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["service_account_id"] == sa_id
    assert data["model_id"] == model_id


async def test_grant_duplicate_access(owner_client: AsyncClient):
    sa_resp = await owner_client.post(
        "/api/v1/auth/service-accounts",
        json={"name": "dup-access", "auth_type": "api_key"},
    )
    sa_id = sa_resp.json()["data"]["service_account"]["id"]

    model_resp = await owner_client.post("/api/v1/models", json={"name": "dup-model"})
    model_id = model_resp.json()["data"]["id"]

    await owner_client.post(
        f"/api/v1/auth/models/{model_id}/access",
        json={"service_account_id": sa_id},
    )
    # Second grant should conflict
    resp = await owner_client.post(
        f"/api/v1/auth/models/{model_id}/access",
        json={"service_account_id": sa_id},
    )
    assert resp.status_code == 409


async def test_list_model_access(owner_client: AsyncClient):
    sa_resp = await owner_client.post(
        "/api/v1/auth/service-accounts",
        json={"name": "list-access", "auth_type": "api_key"},
    )
    sa_id = sa_resp.json()["data"]["service_account"]["id"]

    model_resp = await owner_client.post("/api/v1/models", json={"name": "list-model"})
    model_id = model_resp.json()["data"]["id"]

    await owner_client.post(
        f"/api/v1/auth/models/{model_id}/access",
        json={"service_account_id": sa_id},
    )

    resp = await owner_client.get(f"/api/v1/auth/models/{model_id}/access")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


async def test_revoke_model_access(owner_client: AsyncClient):
    sa_resp = await owner_client.post(
        "/api/v1/auth/service-accounts",
        json={"name": "revoke-access", "auth_type": "api_key"},
    )
    sa_id = sa_resp.json()["data"]["service_account"]["id"]

    model_resp = await owner_client.post("/api/v1/models", json={"name": "revoke-model"})
    model_id = model_resp.json()["data"]["id"]

    await owner_client.post(
        f"/api/v1/auth/models/{model_id}/access",
        json={"service_account_id": sa_id},
    )

    resp = await owner_client.delete(f"/api/v1/auth/models/{model_id}/access/{sa_id}")
    assert resp.status_code == 204


async def test_revoke_model_access_not_found(owner_client: AsyncClient):
    model_resp = await owner_client.post("/api/v1/models", json={"name": "revoke-404"})
    model_id = model_resp.json()["data"]["id"]
    resp = await owner_client.delete(f"/api/v1/auth/models/{model_id}/access/{uuid.uuid4()}")
    assert resp.status_code == 404
