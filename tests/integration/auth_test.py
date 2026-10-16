"""Integration tests for auth API endpoints.

These tests enable auth and exercise the full auth flow:
login, token refresh, logout, user CRUD, service accounts, and model access.
"""

import uuid

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
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
from yaai.server.models.auth import AuthProvider, RefreshToken, User, UserRole
from yaai.server.services.auth_service import AuthService

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


async def test_delete_user_self_not_allowed(owner_client: AsyncClient, seeded_owner: User):
    resp = await owner_client.delete(f"/api/v1/auth/users/{seeded_owner.id}")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Cannot delete your own account"


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


# Access token validation against the database


def _bearer(user: User, role: str | None = None) -> dict[str, str]:
    token = create_access_token(AUTH_CONFIG, str(user.id), role or user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def test_token_of_deleted_user_rejected(
    owner_client: AsyncClient, auth_client: AsyncClient, seeded_viewer: User, db_session: AsyncSession
):
    headers = _bearer(seeded_viewer)
    assert (await auth_client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    assert (await owner_client.delete(f"/api/v1/auth/users/{seeded_viewer.id}")).status_code == 204

    assert (await auth_client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_token_of_deactivated_user_rejected(
    owner_client: AsyncClient, auth_client: AsyncClient, seeded_viewer: User
):
    headers = _bearer(seeded_viewer)
    resp = await owner_client.put(f"/api/v1/auth/users/{seeded_viewer.id}", json={"is_active": False})
    assert resp.status_code == 200

    assert (await auth_client.get("/api/v1/auth/me", headers=headers)).status_code == 401


async def test_role_downgrade_effective_immediately(
    owner_client: AsyncClient, auth_client: AsyncClient, seeded_viewer: User
):
    await owner_client.put(f"/api/v1/auth/users/{seeded_viewer.id}", json={"role": "owner"})
    headers = _bearer(seeded_viewer, role="owner")
    assert (await auth_client.get("/api/v1/auth/users", headers=headers)).status_code == 200

    await owner_client.put(f"/api/v1/auth/users/{seeded_viewer.id}", json={"role": "viewer"})

    # The token still claims "owner", but the database role wins
    assert (await auth_client.get("/api/v1/auth/users", headers=headers)).status_code == 403


async def test_token_with_forged_owner_role_gets_database_role(auth_client: AsyncClient, seeded_viewer: User):
    headers = _bearer(seeded_viewer, role="owner")
    assert (await auth_client.get("/api/v1/auth/users", headers=headers)).status_code == 403


async def test_token_with_malformed_subject_rejected(auth_client: AsyncClient):
    token = create_access_token(AUTH_CONFIG, "not-a-uuid", "owner")
    resp = await auth_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_refresh_rejected_for_deactivated_user(
    owner_client: AsyncClient, auth_client: AsyncClient, seeded_viewer: User
):
    login = await auth_client.post("/api/v1/auth/login", json={"username": "viewer", "password": "viewer-password-123"})
    refresh = login.json()["data"]["refresh_token"]

    await owner_client.put(f"/api/v1/auth/users/{seeded_viewer.id}", json={"is_active": False})

    resp = await auth_client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


async def test_refresh_issues_token_with_current_role(
    owner_client: AsyncClient, auth_client: AsyncClient, seeded_viewer: User
):
    login = await auth_client.post("/api/v1/auth/login", json={"username": "viewer", "password": "viewer-password-123"})
    refresh = login.json()["data"]["refresh_token"]

    await owner_client.put(f"/api/v1/auth/users/{seeded_viewer.id}", json={"role": "owner"})

    resp = await auth_client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 200
    assert resp.json()["data"]["user"]["role"] == "owner"


# Password change hardening


async def test_change_password_revokes_refresh_tokens(auth_client: AsyncClient, seeded_owner: User):
    login = await auth_client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-password-123"})
    tokens = login.json()["data"]
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await auth_client.put(
        "/api/v1/auth/me/password",
        headers=headers,
        json={"current_password": "admin-password-123", "new_password": "new-secure-password"},
    )
    assert resp.status_code == 200

    refresh = await auth_client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401


async def test_user_without_local_password_cannot_set_password(auth_client: AsyncClient, db_session: AsyncSession):
    google_user = User(
        username="google-user",
        email="google-user@example.com",
        hashed_password=None,
        role=UserRole.VIEWER,
        auth_provider=AuthProvider.GOOGLE,
        google_sub="google-sub-123",
        is_active=True,
    )
    db_session.add(google_user)
    await db_session.commit()
    await db_session.refresh(google_user)

    resp = await auth_client.put(
        "/api/v1/auth/me/password",
        headers=_bearer(google_user),
        json={"current_password": "anything", "new_password": "new-secure-password"},
    )
    assert resp.status_code == 400

    await db_session.refresh(google_user)
    assert google_user.hashed_password is None


# Password length (bcrypt 72-byte limit)

TOO_LONG_PASSWORD = "a" * 73


async def test_create_user_with_too_long_password_rejected(owner_client: AsyncClient):
    resp = await owner_client.post(
        "/api/v1/auth/users",
        json={"username": "long-pw", "password": TOO_LONG_PASSWORD, "role": "viewer"},
    )
    assert resp.status_code == 422
    assert "72 bytes" in resp.text


async def test_create_user_with_multibyte_password_over_limit_rejected(owner_client: AsyncClient):
    resp = await owner_client.post(
        "/api/v1/auth/users",
        json={"username": "long-pw-utf8", "password": "ü" * 37, "role": "viewer"},
    )
    assert resp.status_code == 422


async def test_change_password_to_too_long_password_rejected(owner_client: AsyncClient):
    resp = await owner_client.put(
        "/api/v1/auth/me/password",
        json={"current_password": "admin-password-123", "new_password": TOO_LONG_PASSWORD},
    )
    assert resp.status_code == 422


async def test_login_with_too_long_password_returns_401(auth_client: AsyncClient, seeded_owner: User):
    resp = await auth_client.post("/api/v1/auth/login", json={"username": "admin", "password": TOO_LONG_PASSWORD})
    assert resp.status_code == 401


# Role validation


async def test_create_user_with_invalid_role_rejected(owner_client: AsyncClient):
    resp = await owner_client.post(
        "/api/v1/auth/users",
        json={"username": "bad-role", "password": "valid-password-1", "role": "superadmin"},
    )
    assert resp.status_code == 422


async def test_update_user_with_invalid_role_rejected(owner_client: AsyncClient, seeded_viewer: User):
    resp = await owner_client.put(f"/api/v1/auth/users/{seeded_viewer.id}", json={"role": "superadmin"})
    assert resp.status_code == 422


# Model access targets must exist


async def test_grant_access_to_unknown_model_returns_404(owner_client: AsyncClient):
    sa_resp = await owner_client.post(
        "/api/v1/auth/service-accounts", json={"name": "sa-no-model", "auth_type": "api_key"}
    )
    sa_id = sa_resp.json()["data"]["service_account"]["id"]

    resp = await owner_client.post(f"/api/v1/auth/models/{uuid.uuid4()}/access", json={"service_account_id": sa_id})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Model not found"


async def test_grant_access_to_unknown_service_account_returns_404(owner_client: AsyncClient):
    model_resp = await owner_client.post("/api/v1/models", json={"name": "model-no-sa"})
    model_id = model_resp.json()["data"]["id"]

    resp = await owner_client.post(
        f"/api/v1/auth/models/{model_id}/access", json={"service_account_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Service account not found"


async def test_list_access_for_unknown_model_returns_404(owner_client: AsyncClient):
    resp = await owner_client.get(f"/api/v1/auth/models/{uuid.uuid4()}/access")
    assert resp.status_code == 404


async def test_deleted_user_jwt_with_valid_api_key_header_rejected(
    owner_client: AsyncClient, auth_client: AsyncClient, seeded_viewer: User
):
    sa_resp = await owner_client.post(
        "/api/v1/auth/service-accounts", json={"name": "fallthrough-sa", "auth_type": "api_key"}
    )
    raw_key = sa_resp.json()["data"]["raw_key"]
    headers = {**_bearer(seeded_viewer), "X-API-Key": raw_key}

    assert (await auth_client.get("/api/v1/auth/me", headers=headers)).status_code == 200
    assert (await owner_client.delete(f"/api/v1/auth/users/{seeded_viewer.id}")).status_code == 204

    assert (await auth_client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    # The API key on its own is still valid
    assert (await auth_client.get("/api/v1/models", headers={"X-API-Key": raw_key})).status_code == 200


# Self-protection and last-owner guards


async def test_owner_cannot_deactivate_self(owner_client: AsyncClient, seeded_owner: User):
    resp = await owner_client.put(f"/api/v1/auth/users/{seeded_owner.id}", json={"is_active": False})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Cannot deactivate your own account"


async def test_owner_cannot_downgrade_self(owner_client: AsyncClient, seeded_owner: User):
    resp = await owner_client.put(f"/api/v1/auth/users/{seeded_owner.id}", json={"role": "viewer"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Cannot change your own role"


async def test_owner_can_update_own_email_and_keep_role(owner_client: AsyncClient, seeded_owner: User):
    resp = await owner_client.put(
        f"/api/v1/auth/users/{seeded_owner.id}",
        json={"email": "new-admin@example.com", "role": "owner", "is_active": True},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == "new-admin@example.com"


@pytest.mark.parametrize("changes", [{"is_active": False}, {"role": UserRole.VIEWER}])
async def test_last_active_owner_cannot_be_deactivated_or_downgraded(
    db_session: AsyncSession, seeded_owner: User, changes: dict
):
    svc = AuthService(db_session, AUTH_CONFIG)
    with pytest.raises(HTTPException) as exc:
        await svc.update_user(seeded_owner.id, **changes)
    assert exc.value.status_code == 409
    assert exc.value.detail == "At least one active owner is required"


async def test_last_active_owner_cannot_be_deleted(db_session: AsyncSession, seeded_owner: User):
    svc = AuthService(db_session, AUTH_CONFIG)
    with pytest.raises(HTTPException) as exc:
        await svc.delete_user(seeded_owner.id)
    assert exc.value.status_code == 409


async def test_owner_can_be_demoted_when_another_active_owner_exists(
    db_session: AsyncSession, seeded_owner: User, seeded_viewer: User
):
    svc = AuthService(db_session, AUTH_CONFIG)
    await svc.update_user(seeded_viewer.id, role=UserRole.OWNER)

    assert (await svc.update_user(seeded_owner.id, role=UserRole.VIEWER)).role == UserRole.VIEWER
    # seeded_viewer is now the last active owner
    with pytest.raises(HTTPException) as exc:
        await svc.delete_user(seeded_viewer.id)
    assert exc.value.status_code == 409


async def test_inactive_owners_do_not_count_as_active_owners(db_session: AsyncSession, seeded_owner: User):
    inactive_owner = User(
        username="inactive-owner",
        hashed_password=hash_password("inactive-owner-pass"),
        role=UserRole.OWNER,
        auth_provider=AuthProvider.LOCAL,
        is_active=False,
    )
    db_session.add(inactive_owner)
    await db_session.commit()

    svc = AuthService(db_session, AUTH_CONFIG)
    with pytest.raises(HTTPException) as exc:
        await svc.update_user(seeded_owner.id, is_active=False)
    assert exc.value.status_code == 409
    # Removing an already inactive owner is always fine
    assert await svc.delete_user(inactive_owner.id) is True


async def test_change_password_revokes_refresh_tokens_in_one_commit(db_session: AsyncSession, seeded_owner: User):
    svc = AuthService(db_session, AUTH_CONFIG)
    await svc.create_tokens(seeded_owner)

    commits = 0
    original_commit = db_session.commit

    async def counting_commit():
        nonlocal commits
        commits += 1
        await original_commit()

    db_session.commit = counting_commit
    await svc.change_password(seeded_owner, "brand-new-password")

    assert commits == 1
    remaining = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == seeded_owner.id))
    assert remaining.scalars().all() == []
