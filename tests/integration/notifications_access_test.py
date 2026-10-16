"""Access control and per-reader read state for notifications against real PostgreSQL."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.integration.auth_separation_test import _create_sa, _grant_access, _make_sa_client
from tests.integration.conftest import PG_AVAILABLE
from tests.integration.notifications_test import _setup_drifted

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="Docker not available")


async def _first_notification_id(client: AsyncClient) -> str:
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200, resp.text
    return resp.json()["data"][0]["id"]


# S2: access check on PATCH


async def test_sa_without_access_cannot_mark_notification_read(
    owner_client: AsyncClient, pg_session_factory: async_sessionmaker
):
    await _setup_drifted(owner_client)
    notification_id = await _first_notification_id(owner_client)
    _, raw_key = await _create_sa(owner_client, "no-access-sa")

    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        resp = await sa_client.patch(f"/api/v1/notifications/{notification_id}", json={"is_read": True})
        assert resp.status_code == 403

    resp = await owner_client.get("/api/v1/notifications", params={"is_read": False})
    assert notification_id in [n["id"] for n in resp.json()["data"]]


async def test_sa_with_access_can_mark_notification_read(
    owner_client: AsyncClient, pg_session_factory: async_sessionmaker
):
    model_id, _, _ = await _setup_drifted(owner_client)
    notification_id = await _first_notification_id(owner_client)
    sa_id, raw_key = await _create_sa(owner_client, "access-sa")
    await _grant_access(owner_client, model_id, sa_id)

    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        resp = await sa_client.patch(f"/api/v1/notifications/{notification_id}", json={"is_read": True})
        assert resp.status_code == 200
        assert resp.json()["data"]["is_read"] is True


async def test_sa_access_to_other_model_does_not_allow_marking(
    owner_client: AsyncClient, pg_session_factory: async_sessionmaker
):
    await _setup_drifted(owner_client, model_name="notif-model-a")
    notification_id = await _first_notification_id(owner_client)
    other_model = await owner_client.post("/api/v1/models", json={"name": "unrelated-model"})
    sa_id, raw_key = await _create_sa(owner_client, "other-model-sa")
    await _grant_access(owner_client, other_model.json()["data"]["id"], sa_id)

    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        resp = await sa_client.patch(f"/api/v1/notifications/{notification_id}", json={"is_read": True})
        assert resp.status_code == 403


async def test_mark_nonexistent_notification_returns_404(owner_client: AsyncClient):
    resp = await owner_client.patch(
        "/api/v1/notifications/00000000-0000-0000-0000-0000000000aa", json={"is_read": True}
    )
    assert resp.status_code == 404
