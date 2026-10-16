"""Local JWT auth integration tests against real PostgreSQL.

Every request uses its own database session (as in production), covering the
database-checked access token path for deleted, deactivated and downgraded users.
"""

import pytest
from httpx import AsyncClient

from tests.integration.conftest import PG_AVAILABLE
from yaai.server.models.auth import User

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="Docker not available")


async def test_deactivated_user_jwt_rejected(
    owner_client: AsyncClient, viewer_client: AsyncClient, seeded_viewer: User
):
    assert (await viewer_client.get("/api/v1/auth/me")).status_code == 200

    resp = await owner_client.put(f"/api/v1/auth/users/{seeded_viewer.id}", json={"is_active": False})
    assert resp.status_code == 200

    assert (await viewer_client.get("/api/v1/auth/me")).status_code == 401


async def test_deleted_user_jwt_rejected(owner_client: AsyncClient, viewer_client: AsyncClient, seeded_viewer: User):
    assert (await viewer_client.get("/api/v1/auth/me")).status_code == 200

    assert (await owner_client.delete(f"/api/v1/auth/users/{seeded_viewer.id}")).status_code == 204

    assert (await viewer_client.get("/api/v1/auth/me")).status_code == 401


async def test_downgraded_owner_loses_owner_access(
    owner_client: AsyncClient, viewer_client: AsyncClient, seeded_viewer: User
):
    # The token always claims "viewer"; only the database role decides
    await owner_client.put(f"/api/v1/auth/users/{seeded_viewer.id}", json={"role": "owner"})
    assert (await viewer_client.get("/api/v1/auth/users")).status_code == 200

    await owner_client.put(f"/api/v1/auth/users/{seeded_viewer.id}", json={"role": "viewer"})

    assert (await viewer_client.get("/api/v1/auth/users")).status_code == 403
