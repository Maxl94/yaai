"""Access control and per-reader read state for notifications against real PostgreSQL."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.auth_separation_test import _create_sa, _grant_access, _make_sa_client
from tests.integration.conftest import AUTH_CONFIG, PG_AVAILABLE, make_pg_app
from tests.integration.notifications_test import _setup_drifted
from yaai.server.auth.jwt import create_access_token
from yaai.server.auth.passwords import hash_password
from yaai.server.models.auth import AuthProvider, User, UserRole
from yaai.server.models.job import Notification, NotificationReadReceipt

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


# P6: per-reader read state


async def _make_user_client(pg_session_factory: async_sessionmaker, pg_db: AsyncSession, name: str) -> AsyncClient:
    """Seed a viewer user and return a client authenticated as that user."""
    user = User(
        username=name,
        email=f"{name}@example.com",
        hashed_password=hash_password("viewer-pass-123"),
        role=UserRole.VIEWER,
        auth_provider=AuthProvider.LOCAL,
        is_active=True,
    )
    pg_db.add(user)
    await pg_db.commit()
    await pg_db.refresh(user)
    app = make_pg_app(pg_session_factory, AUTH_CONFIG)
    token = create_access_token(AUTH_CONFIG, str(user.id), "viewer")
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    client = AsyncClient(transport=transport, base_url="http://test", headers={"Authorization": f"Bearer {token}"})
    client.user_id = user.id  # type: ignore[attr-defined]
    return client


async def _unread_ids(client: AsyncClient) -> set[str]:
    resp = await client.get("/api/v1/notifications", params={"is_read": False})
    assert resp.status_code == 200, resp.text
    return {n["id"] for n in resp.json()["data"]}


async def test_mark_read_is_per_user(
    owner_client: AsyncClient, viewer_client: AsyncClient, pg_session_factory: async_sessionmaker
):
    await _setup_drifted(owner_client)
    notification_id = await _first_notification_id(owner_client)

    resp = await viewer_client.patch(f"/api/v1/notifications/{notification_id}", json={"is_read": True})
    assert resp.status_code == 200
    assert resp.json()["data"]["is_read"] is True

    assert notification_id not in await _unread_ids(viewer_client)
    assert notification_id in await _unread_ids(owner_client)
    owner_view = (await owner_client.get("/api/v1/notifications")).json()["data"]
    assert next(n for n in owner_view if n["id"] == notification_id)["is_read"] is False


async def test_mark_read_twice_is_idempotent(owner_client: AsyncClient, pg_db: AsyncSession):
    await _setup_drifted(owner_client)
    notification_id = await _first_notification_id(owner_client)

    for _ in range(2):
        resp = await owner_client.patch(f"/api/v1/notifications/{notification_id}", json={"is_read": True})
        assert resp.status_code == 200

    count = (await pg_db.execute(select(func.count()).select_from(NotificationReadReceipt))).scalar_one()
    assert count == 1


async def test_mark_all_read_is_per_user(
    owner_client: AsyncClient, viewer_client: AsyncClient, pg_session_factory: async_sessionmaker
):
    await _setup_drifted(owner_client)
    total = len(await _unread_ids(owner_client))
    assert total > 0

    resp = await viewer_client.post("/api/v1/notifications/mark-all-read")
    assert resp.json()["data"]["marked_read"] == total
    assert await _unread_ids(viewer_client) == set()
    assert len(await _unread_ids(owner_client)) == total

    resp = await viewer_client.post("/api/v1/notifications/mark-all-read")
    assert resp.json()["data"]["marked_read"] == 0


async def test_is_read_filter_applies_per_user(owner_client: AsyncClient, viewer_client: AsyncClient):
    await _setup_drifted(owner_client)
    notification_id = await _first_notification_id(owner_client)
    await viewer_client.patch(f"/api/v1/notifications/{notification_id}", json={"is_read": True})

    read_resp = await viewer_client.get("/api/v1/notifications", params={"is_read": True})
    assert [n["id"] for n in read_resp.json()["data"]] == [notification_id]
    assert read_resp.json()["meta"]["total"] == 1
    owner_read = await owner_client.get("/api/v1/notifications", params={"is_read": True})
    assert owner_read.json()["data"] == []


async def test_sa_read_state_is_separate(owner_client: AsyncClient, pg_session_factory: async_sessionmaker):
    model_id, _, _ = await _setup_drifted(owner_client)
    notification_id = await _first_notification_id(owner_client)
    sa_id, raw_key = await _create_sa(owner_client, "reader-sa")
    await _grant_access(owner_client, model_id, sa_id)

    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        assert notification_id in await _unread_ids(sa_client)
        resp = await sa_client.post("/api/v1/notifications/mark-all-read")
        assert resp.json()["data"]["marked_read"] >= 1
        assert await _unread_ids(sa_client) == set()

    assert notification_id in await _unread_ids(owner_client)


async def test_sa_mark_all_read_only_marks_accessible_models(
    owner_client: AsyncClient, pg_session_factory: async_sessionmaker
):
    model_a, _, _ = await _setup_drifted(owner_client, model_name="notif-model-a")
    await _setup_drifted(owner_client, model_name="notif-model-b")
    all_unread = await _unread_ids(owner_client)
    sa_id, raw_key = await _create_sa(owner_client, "scoped-sa")
    await _grant_access(owner_client, model_a, sa_id)

    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        visible = await _unread_ids(sa_client)
        assert 0 < len(visible) < len(all_unread)
        resp = await sa_client.post("/api/v1/notifications/mark-all-read")
        assert resp.json()["data"]["marked_read"] == len(visible)


async def test_deleting_user_cascades_read_receipts(
    owner_client: AsyncClient, pg_session_factory: async_sessionmaker, pg_db: AsyncSession
):
    await _setup_drifted(owner_client)
    notification_id = await _first_notification_id(owner_client)
    reader_client = await _make_user_client(pg_session_factory, pg_db, "cascade-user")
    async with reader_client:
        await reader_client.patch(f"/api/v1/notifications/{notification_id}", json={"is_read": True})
    user_id = reader_client.user_id  # type: ignore[attr-defined]

    stmt = select(func.count()).select_from(NotificationReadReceipt).where(NotificationReadReceipt.user_id == user_id)
    assert (await pg_db.execute(stmt)).scalar_one() == 1

    await pg_db.execute(delete(User).where(User.id == user_id))
    await pg_db.commit()
    assert (await pg_db.execute(stmt)).scalar_one() == 0


async def test_deleting_notification_cascades_read_receipts(owner_client: AsyncClient, pg_db: AsyncSession):
    await _setup_drifted(owner_client)
    notification_id = await _first_notification_id(owner_client)
    await owner_client.patch(f"/api/v1/notifications/{notification_id}", json={"is_read": True})

    await pg_db.execute(delete(Notification).where(Notification.id == uuid.UUID(notification_id)))
    await pg_db.commit()
    count = (await pg_db.execute(select(func.count()).select_from(NotificationReadReceipt))).scalar_one()
    assert count == 0


async def test_receipt_requires_exactly_one_reader(owner_client: AsyncClient, pg_db: AsyncSession):
    await _setup_drifted(owner_client)
    notification_id = uuid.UUID(await _first_notification_id(owner_client))

    pg_db.add(NotificationReadReceipt(notification_id=notification_id))
    with pytest.raises(IntegrityError):
        await pg_db.commit()
    await pg_db.rollback()


async def test_deleted_user_with_valid_token_gets_401(
    owner_client: AsyncClient, pg_session_factory: async_sessionmaker, pg_db: AsyncSession
):
    await _setup_drifted(owner_client)
    notification_id = await _first_notification_id(owner_client)
    ghost_client = await _make_user_client(pg_session_factory, pg_db, "ghost-user")
    await pg_db.execute(delete(User).where(User.id == ghost_client.user_id))  # type: ignore[attr-defined]
    await pg_db.commit()

    async with ghost_client:
        resp = await ghost_client.patch(f"/api/v1/notifications/{notification_id}", json={"is_read": True})
        assert resp.status_code == 401
