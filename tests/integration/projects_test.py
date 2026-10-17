"""Project-based access control integration tests against real PostgreSQL (auth enabled)."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.auth_separation_test import _create_sa, _create_version, _make_sa_client
from tests.integration.conftest import AUTH_CONFIG, PG_AVAILABLE, make_pg_app
from tests.integration.notifications_test import _setup_drifted
from yaai.server.auth.jwt import create_access_token
from yaai.server.auth.passwords import hash_password
from yaai.server.models.auth import AuthProvider, User, UserRole

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="Docker not available")

API = "/api/v1"


# Helpers


async def _create_project(owner_client: AsyncClient, name: str) -> dict:
    resp = await owner_client.post(f"{API}/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _add_member(client: AsyncClient, project_id: str, role: str, **principal) -> dict:
    resp = await client.post(f"{API}/projects/{project_id}/members", json={"role": role, **principal})
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _create_user(pg_db: AsyncSession, name: str, role: UserRole = UserRole.VIEWER) -> User:
    user = User(
        username=name,
        email=f"{name}@example.com",
        hashed_password=hash_password("user-pass-12345"),
        role=role,
        auth_provider=AuthProvider.LOCAL,
        is_active=True,
    )
    pg_db.add(user)
    await pg_db.commit()
    await pg_db.refresh(user)
    return user


def _client_for(factory: async_sessionmaker, user: User) -> AsyncClient:
    app = make_pg_app(factory, AUTH_CONFIG)
    token = create_access_token(AUTH_CONFIG, str(user.id), user.role.value)
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _create_model(client: AsyncClient, name: str, project_id: str | None = None):
    payload = {"name": name} if project_id is None else {"name": name, "project_id": project_id}
    return await client.post(f"{API}/models", json=payload)


async def _model_in_project(owner_client: AsyncClient, name: str, project_id: str) -> dict:
    resp = await _create_model(owner_client, name, project_id)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _default_project_id(owner_client: AsyncClient) -> str:
    projects = (await owner_client.get(f"{API}/projects")).json()["data"]
    return next(p["id"] for p in projects if p["is_default"])


class Team:
    """Project A with owner/editor/viewer members, project B that none of them belongs to."""

    owner_client: AsyncClient
    project_a: dict
    project_b: dict
    users: dict[str, User]
    clients: dict[str, AsyncClient]


@pytest.fixture
async def team(owner_client: AsyncClient, pg_db: AsyncSession, pg_session_factory: async_sessionmaker):
    t = Team()
    t.owner_client = owner_client
    t.project_a = await _create_project(owner_client, "project-a")
    t.project_b = await _create_project(owner_client, "project-b")
    t.users, t.clients = {}, {}
    for name, role in (("a-owner", "owner"), ("a-editor", "editor"), ("a-viewer", "viewer"), ("outsider", None)):
        t.users[name] = await _create_user(pg_db, name)
        t.clients[name] = _client_for(pg_session_factory, t.users[name])
        if role:
            await _add_member(owner_client, t.project_a["id"], role, user_id=str(t.users[name].id))
    yield t
    for client in t.clients.values():
        await client.aclose()


# Project CRUD


async def test_global_owner_creates_lists_and_deletes_projects(owner_client: AsyncClient):
    project = await _create_project(owner_client, "analytics")
    assert project["my_role"] == "owner"
    assert project["model_count"] == 0
    assert project["is_default"] is False

    duplicate = await owner_client.post(f"{API}/projects", json={"name": "analytics"})
    assert duplicate.status_code == 409

    await _model_in_project(owner_client, "m1", project["id"])
    listed = {p["name"]: p for p in (await owner_client.get(f"{API}/projects")).json()["data"]}
    assert listed["analytics"]["model_count"] == 1

    assert (await owner_client.delete(f"{API}/projects/{project['id']}")).status_code == 409  # still has models
    models = (await owner_client.get(f"{API}/models", params={"project_id": project["id"]})).json()["data"]
    assert (await owner_client.delete(f"{API}/models/{models[0]['id']}")).status_code == 204
    assert (await owner_client.delete(f"{API}/projects/{project['id']}")).status_code == 204
    assert (await owner_client.get(f"{API}/projects/{project['id']}")).status_code == 404


async def test_default_project_cannot_be_deleted_or_renamed(owner_client: AsyncClient):
    await _create_model(owner_client, "creates-default-project")
    default_id = await _default_project_id(owner_client)

    assert (await owner_client.delete(f"{API}/projects/{default_id}")).status_code == 409
    assert (await owner_client.patch(f"{API}/projects/{default_id}", json={"name": "renamed"})).status_code == 409
    ok = await owner_client.patch(f"{API}/projects/{default_id}", json={"description": "everything else"})
    assert ok.status_code == 200
    assert ok.json()["data"]["description"] == "everything else"


async def test_only_global_owner_can_create_or_delete_projects(team: Team):
    for name in ("a-owner", "a-editor", "a-viewer", "outsider"):
        resp = await team.clients[name].post(f"{API}/projects", json={"name": f"by-{name}"})
        assert resp.status_code == 403, name
        resp = await team.clients[name].delete(f"{API}/projects/{team.project_a['id']}")
        assert resp.status_code == 403, name


async def test_users_list_only_their_projects_with_role(team: Team):
    mine = (await team.clients["a-editor"].get(f"{API}/projects")).json()["data"]
    assert [(p["name"], p["my_role"]) for p in mine] == [("project-a", "editor")]
    assert (await team.clients["outsider"].get(f"{API}/projects")).json()["data"] == []
    everything = {p["name"] for p in (await team.owner_client.get(f"{API}/projects")).json()["data"]}
    assert {"project-a", "project-b"} <= everything


async def test_project_detail_requires_membership(team: Team):
    resp = await team.clients["a-viewer"].get(f"{API}/projects/{team.project_a['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["my_role"] == "viewer"
    assert (await team.clients["a-viewer"].get(f"{API}/projects/{team.project_b['id']}")).status_code == 403
    assert (await team.clients["a-viewer"].get(f"{API}/projects/{uuid.uuid4()}")).status_code == 404


async def test_project_owner_can_edit_project_but_viewer_cannot(team: Team):
    url = f"{API}/projects/{team.project_a['id']}"
    resp = await team.clients["a-owner"].patch(url, json={"description": "ours"})
    assert resp.status_code == 200
    assert resp.json()["data"]["description"] == "ours"
    assert (await team.clients["a-editor"].patch(url, json={"description": "x"})).status_code == 403
    assert (await team.clients["a-owner"].patch(url, json={"name": "project-b"})).status_code == 409
    other = f"{API}/projects/{team.project_b['id']}"
    assert (await team.clients["a-owner"].patch(other, json={"description": "x"})).status_code == 403


# Membership management


async def test_project_owner_manages_members(team: Team, pg_db: AsyncSession):
    client = team.clients["a-owner"]
    newcomer = await _create_user(pg_db, "newcomer")
    base = f"{API}/projects/{team.project_a['id']}/members"

    added = await _add_member(client, team.project_a["id"], "viewer", username="newcomer")
    assert (added["name"], added["email"], added["role"], added["principal_type"]) == (
        "newcomer",
        "newcomer@example.com",
        "viewer",
        "user",
    )
    assert added["user_id"] == str(newcomer.id)

    assert (await client.post(base, json={"role": "editor", "user_id": str(newcomer.id)})).status_code == 409
    assert (await client.post(base, json={"role": "editor", "user_id": str(uuid.uuid4())})).status_code == 404
    assert (await client.post(base, json={"role": "editor", "username": "nobody"})).status_code == 404
    assert (await client.post(base, json={"role": "editor"})).status_code == 422
    both = {"role": "editor", "user_id": str(newcomer.id), "service_account_id": str(uuid.uuid4())}
    assert (await client.post(base, json=both)).status_code == 422

    promoted = await client.patch(f"{base}/{added['id']}", json={"role": "editor"})
    assert promoted.status_code == 200
    assert promoted.json()["data"]["role"] == "editor"

    members = (await client.get(base)).json()["data"]
    assert {m["name"] for m in members} == {"a-owner", "a-editor", "a-viewer", "newcomer"}

    assert (await client.delete(f"{base}/{added['id']}")).status_code == 204
    assert (await client.delete(f"{base}/{added['id']}")).status_code == 404
    assert len((await client.get(base)).json()["data"]) == 3


async def test_non_admins_cannot_manage_members(team: Team):
    base = f"{API}/projects/{team.project_a['id']}/members"
    member_id = (await team.owner_client.get(base)).json()["data"][0]["id"]
    for name in ("a-editor", "a-viewer", "outsider"):
        client = team.clients[name]
        assert (await client.get(base)).status_code == 403, name
        assert (await client.post(base, json={"role": "viewer", "username": "outsider"})).status_code == 403, name
        assert (await client.patch(f"{base}/{member_id}", json={"role": "owner"})).status_code == 403, name
        assert (await client.delete(f"{base}/{member_id}")).status_code == 403, name


async def test_project_owner_cannot_manage_other_projects(team: Team):
    base = f"{API}/projects/{team.project_b['id']}/members"
    client = team.clients["a-owner"]
    assert (await client.get(base)).status_code == 403
    assert (await client.post(base, json={"role": "viewer", "username": "outsider"})).status_code == 403


async def test_membership_of_other_project_is_not_reachable_via_this_project(team: Team):
    member = await _add_member(
        team.owner_client, team.project_b["id"], "viewer", user_id=str(team.users["outsider"].id)
    )
    url = f"{API}/projects/{team.project_a['id']}/members/{member['id']}"
    assert (await team.clients["a-owner"].delete(url)).status_code == 404
    assert (await team.clients["a-owner"].patch(url, json={"role": "owner"})).status_code == 404


async def test_service_account_can_be_added_as_member(team: Team):
    sa_id, _ = await _create_sa(team.owner_client, "member-sa")
    member = await _add_member(team.clients["a-owner"], team.project_a["id"], "editor", service_account_id=sa_id)
    assert member["principal_type"] == "service_account"
    assert member["name"] == "member-sa"
    assert member["user_id"] is None
    base = f"{API}/projects/{team.project_a['id']}/members"
    assert (
        await team.clients["a-owner"].post(base, json={"role": "viewer", "service_account_id": sa_id})
    ).status_code == 409
    unknown = {"role": "viewer", "service_account_id": str(uuid.uuid4())}
    assert (await team.clients["a-owner"].post(base, json=unknown)).status_code == 404


async def test_removed_member_loses_access_immediately(team: Team):
    model = await _model_in_project(team.owner_client, "revoked-model", team.project_a["id"])
    url = f"{API}/models/{model['id']}"
    assert (await team.clients["a-viewer"].get(url)).status_code == 200

    members = (await team.owner_client.get(f"{API}/projects/{team.project_a['id']}/members")).json()["data"]
    membership = next(m for m in members if m["name"] == "a-viewer")
    await team.owner_client.delete(f"{API}/projects/{team.project_a['id']}/members/{membership['id']}")

    assert (await team.clients["a-viewer"].get(url)).status_code == 403


# Read isolation


async def test_non_member_cannot_list_or_read_models(team: Team):
    model_a = await _model_in_project(team.owner_client, "iso-a", team.project_a["id"])
    model_b = await _model_in_project(team.owner_client, "iso-b", team.project_b["id"])
    version_b = await _create_version(team.owner_client, model_b["id"])

    outsider = team.clients["outsider"]
    assert (await outsider.get(f"{API}/models")).json()["data"] == []
    assert (await outsider.get(f"{API}/models/{model_a['id']}")).status_code == 403
    assert (await outsider.get(f"{API}/models/{model_b['id']}/versions/{version_b['id']}")).status_code == 403

    member_view = (await team.clients["a-viewer"].get(f"{API}/models")).json()
    assert [m["name"] for m in member_view["data"]] == ["iso-a"]
    assert member_view["meta"]["total"] == 1
    assert (await team.clients["a-viewer"].get(f"{API}/models/{model_b['id']}")).status_code == 403


async def test_models_list_filters_by_project(team: Team):
    await _model_in_project(team.owner_client, "in-a", team.project_a["id"])
    await _model_in_project(team.owner_client, "in-b", team.project_b["id"])

    resp = await team.owner_client.get(f"{API}/models", params={"project_id": team.project_b["id"]})
    assert [m["name"] for m in resp.json()["data"]] == ["in-b"]
    assert resp.json()["data"][0]["project_name"] == "project-b"
    both = await team.owner_client.get(f"{API}/models")
    assert {m["name"] for m in both.json()["data"]} == {"in-a", "in-b"}
    # filtering by a foreign project never leaks models
    leak = await team.clients["a-viewer"].get(f"{API}/models", params={"project_id": team.project_b["id"]})
    assert leak.json()["data"] == []


async def test_non_member_cannot_read_monitoring_data(team: Team):
    model_id, version_id, job_id = await _setup_drifted(team.owner_client, "monitored")
    await team.owner_client.patch(f"{API}/models/{model_id}", json={"project_id": team.project_a["id"]})
    base = f"{API}/models/{model_id}/versions/{version_id}"
    reads = [
        f"{base}/dashboard",
        f"{base}/dashboard/compare?mode=vs_reference&from_a=2020-01-01T00:00:00Z&to_a=2030-01-01T00:00:00Z",
        f"{base}/inference-volume",
        f"{base}/drift-results",
        f"{base}/jobs",
        f"{API}/jobs/{job_id}",
        f"{API}/jobs/{job_id}/runs",
    ]
    for url in reads:
        assert (await team.clients["a-viewer"].get(url)).status_code == 200, url
        assert (await team.clients["outsider"].get(url)).status_code == 403, url
    for listing in ("jobs", "drift-overview"):
        assert (await team.clients["a-viewer"].get(f"{API}/{listing}")).json()["meta"]["total"] >= 1, listing
        assert (await team.clients["outsider"].get(f"{API}/{listing}")).json()["meta"]["total"] == 0, listing


async def test_notifications_are_scoped_to_member_projects(team: Team):
    model_id, version_id, _ = await _setup_drifted(team.owner_client, "notif-scope")
    await team.owner_client.patch(f"{API}/models/{model_id}", json={"project_id": team.project_a["id"]})

    member = team.clients["a-viewer"]
    outsider = team.clients["outsider"]
    notifications = (await member.get(f"{API}/notifications")).json()["data"]
    assert notifications
    assert (await outsider.get(f"{API}/notifications")).json()["data"] == []

    notification_id = notifications[0]["id"]
    assert (await outsider.patch(f"{API}/notifications/{notification_id}", json={"is_read": True})).status_code == 403
    assert (await outsider.post(f"{API}/notifications/mark-all-read")).json()["data"]["marked_read"] == 0
    assert (await member.patch(f"{API}/notifications/{notification_id}", json={"is_read": True})).status_code == 200


# Write permissions


async def test_editor_can_write_viewer_cannot(team: Team):
    model = await _model_in_project(team.owner_client, "write-model", team.project_a["id"])
    version = await _create_version(team.owner_client, model["id"])
    version_payload = {"model_version_id": version["id"], "inputs": {"age": 3}, "outputs": {"score": 0.1}}
    schema_payload = [
        {"direction": "input", "field_name": "age", "data_type": "numerical"},
        {"direction": "output", "field_name": "score", "data_type": "numerical"},
    ]

    editor, viewer = team.clients["a-editor"], team.clients["a-viewer"]
    assert (await editor.post(f"{API}/inferences", json=version_payload)).status_code == 201
    assert (await editor.put(f"{API}/models/{model['id']}", json={"description": "edited"})).status_code == 200
    created = await editor.post(
        f"{API}/models/{model['id']}/versions", json={"version": "v2", "schema": schema_payload}
    )
    assert created.status_code == 201

    assert (await viewer.post(f"{API}/inferences", json=version_payload)).status_code == 403
    assert (await viewer.put(f"{API}/models/{model['id']}", json={"description": "x"})).status_code == 403
    denied = await viewer.post(f"{API}/models/{model['id']}/versions", json={"version": "v3", "schema": schema_payload})
    assert denied.status_code == 403


async def test_project_editor_cannot_write_to_other_project(team: Team):
    model_b = await _model_in_project(team.owner_client, "foreign", team.project_b["id"])
    version_b = await _create_version(team.owner_client, model_b["id"])
    editor = team.clients["a-editor"]
    payload = {"model_version_id": version_b["id"], "inputs": {"age": 3}, "outputs": {"score": 0.1}}

    assert (await editor.post(f"{API}/inferences", json=payload)).status_code == 403
    assert (await editor.put(f"{API}/models/{model_b['id']}", json={"description": "x"})).status_code == 403


async def test_only_global_owner_deletes_models(team: Team):
    model = await _model_in_project(team.owner_client, "undeletable", team.project_a["id"])
    assert (await team.clients["a-owner"].delete(f"{API}/models/{model['id']}")).status_code == 403
    assert (await team.owner_client.delete(f"{API}/models/{model['id']}")).status_code == 204


# Model creation


async def test_model_creation_per_role(team: Team):
    for name, expected in (("a-owner", 201), ("a-editor", 201), ("a-viewer", 403), ("outsider", 403)):
        resp = await _create_model(team.clients[name], f"by-{name}", team.project_a["id"])
        assert resp.status_code == expected, name
    created = await _create_model(team.owner_client, "by-global-owner", team.project_b["id"])
    assert created.status_code == 201
    assert created.json()["data"]["project_id"] == team.project_b["id"]
    assert created.json()["data"]["project_name"] == "project-b"


async def test_editor_cannot_create_model_in_default_project_or_other_project(team: Team):
    assert (await _create_model(team.clients["a-editor"], "no-project")).status_code == 403  # default project
    assert (await _create_model(team.clients["a-editor"], "other", team.project_b["id"])).status_code == 403


async def test_model_creation_defaults_to_default_project(owner_client: AsyncClient):
    created = (await _create_model(owner_client, "defaulted")).json()["data"]
    assert created["project_name"] == "default"
    assert created["project_id"] == await _default_project_id(owner_client)


async def test_model_creation_in_unknown_project_is_404(owner_client: AsyncClient):
    assert (await _create_model(owner_client, "ghost", str(uuid.uuid4()))).status_code == 404


async def test_model_names_are_unique_per_project(team: Team):
    first = await _create_model(team.owner_client, "same-name", team.project_a["id"])
    other_project = await _create_model(team.owner_client, "same-name", team.project_b["id"])
    clash = await _create_model(team.owner_client, "same-name", team.project_a["id"])

    assert first.status_code == 201
    assert other_project.status_code == 201
    assert clash.status_code == 409
    rename = await team.owner_client.put(f"{API}/models/{other_project.json()['data']['id']}", json={"name": "other"})
    assert rename.status_code == 200


# Moving models


async def test_global_owner_moves_models_between_projects(team: Team):
    model = await _model_in_project(team.owner_client, "mover", team.project_a["id"])

    moved = await team.owner_client.patch(f"{API}/models/{model['id']}", json={"project_id": team.project_b["id"]})

    assert moved.status_code == 200
    assert moved.json()["data"]["project_id"] == team.project_b["id"]
    assert moved.json()["data"]["project_name"] == "project-b"
    assert (await team.clients["a-viewer"].get(f"{API}/models/{model['id']}")).status_code == 403
    moved_back = await team.owner_client.put(f"{API}/models/{model['id']}", json={"project_id": team.project_a["id"]})
    assert moved_back.status_code == 200
    assert (await team.clients["a-viewer"].get(f"{API}/models/{model['id']}")).status_code == 200


async def test_moving_models_is_denied_for_non_global_owners(team: Team):
    model = await _model_in_project(team.owner_client, "pinned", team.project_a["id"])
    for name in ("a-owner", "a-editor", "a-viewer", "outsider"):
        resp = await team.clients[name].patch(f"{API}/models/{model['id']}", json={"project_id": team.project_b["id"]})
        assert resp.status_code == 403, name
    assert (await team.owner_client.get(f"{API}/models/{model['id']}")).json()["data"]["project_id"] == team.project_a[
        "id"
    ]


async def test_editor_can_patch_model_without_moving_it(team: Team):
    model = await _model_in_project(team.owner_client, "same-place", team.project_a["id"])
    resp = await team.clients["a-editor"].patch(
        f"{API}/models/{model['id']}", json={"project_id": team.project_a["id"], "description": "d"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["description"] == "d"


async def test_move_errors(team: Team):
    model = await _model_in_project(team.owner_client, "clashing", team.project_a["id"])
    await _model_in_project(team.owner_client, "clashing", team.project_b["id"])

    unknown = await team.owner_client.patch(f"{API}/models/{model['id']}", json={"project_id": str(uuid.uuid4())})
    clash = await team.owner_client.patch(f"{API}/models/{model['id']}", json={"project_id": team.project_b["id"]})

    assert unknown.status_code == 404
    assert clash.status_code == 409
    assert (await team.owner_client.get(f"{API}/models/{model['id']}")).json()["data"]["project_id"] == team.project_a[
        "id"
    ]


# Service accounts


async def test_sa_without_membership_creates_in_default_project_and_gets_access(
    owner_client: AsyncClient, pg_session_factory: async_sessionmaker
):
    _, raw_key = await _create_sa(owner_client, "legacy-sdk-sa")
    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        resp = await sa_client.post(f"{API}/models", json={"name": "sdk-model"})
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["project_name"] == "default"
        assert (await sa_client.get(f"{API}/models/{data['id']}")).status_code == 200


async def test_sa_without_membership_cannot_create_in_other_projects(
    team: Team, pg_session_factory: async_sessionmaker
):
    _, raw_key = await _create_sa(team.owner_client, "outsider-sa")
    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        assert (await _create_model(sa_client, "nope", team.project_a["id"])).status_code == 403
        await _model_in_project(team.owner_client, "hidden", team.project_a["id"])
        assert (await sa_client.get(f"{API}/models")).json()["data"] == []


async def test_sa_project_membership_grants_access(team: Team, pg_session_factory: async_sessionmaker):
    editor_id, editor_key = await _create_sa(team.owner_client, "editor-sa")
    viewer_id, viewer_key = await _create_sa(team.owner_client, "viewer-sa")
    await _add_member(team.owner_client, team.project_a["id"], "editor", service_account_id=editor_id)
    await _add_member(team.owner_client, team.project_a["id"], "viewer", service_account_id=viewer_id)
    model = await _model_in_project(team.owner_client, "sa-shared", team.project_a["id"])
    version = await _create_version(team.owner_client, model["id"])
    payload = {"model_version_id": version["id"], "inputs": {"age": 3}, "outputs": {"score": 0.1}}

    async with await _make_sa_client(pg_session_factory, editor_key) as editor_sa:
        assert [m["name"] for m in (await editor_sa.get(f"{API}/models")).json()["data"]] == ["sa-shared"]
        assert (await editor_sa.post(f"{API}/inferences", json=payload)).status_code == 201
        created = await _create_model(editor_sa, "sa-in-project", team.project_a["id"])
        assert created.status_code == 201
        assert (await _create_model(editor_sa, "sa-elsewhere", team.project_b["id"])).status_code == 403
    async with await _make_sa_client(pg_session_factory, viewer_key) as viewer_sa:
        assert (await viewer_sa.get(f"{API}/models/{model['id']}")).status_code == 200
        assert (await viewer_sa.post(f"{API}/inferences", json=payload)).status_code == 403
        assert (await _create_model(viewer_sa, "viewer-sa-model", team.project_a["id"])).status_code == 403


async def test_sa_model_access_still_works_across_projects(team: Team, pg_session_factory: async_sessionmaker):
    sa_id, raw_key = await _create_sa(team.owner_client, "acl-sa")
    model = await _model_in_project(team.owner_client, "acl-model", team.project_b["id"])
    grant = await team.owner_client.post(f"{API}/auth/models/{model['id']}/access", json={"service_account_id": sa_id})
    assert grant.status_code == 201

    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        assert (await sa_client.get(f"{API}/models/{model['id']}")).status_code == 200
        assert (await sa_client.put(f"{API}/models/{model['id']}", json={"description": "x"})).status_code == 200
        assert [m["name"] for m in (await sa_client.get(f"{API}/models")).json()["data"]] == ["acl-model"]


# Hardening: SA access grants, reserved name, owner rules, cascades


async def _membership_id(client: AsyncClient, project_id: str, name: str) -> str:
    members = (await client.get(f"{API}/projects/{project_id}/members")).json()["data"]
    return next(m["id"] for m in members if m["name"] == name)


async def test_sa_created_model_in_member_project_is_revoked_with_membership(
    team: Team, pg_session_factory: async_sessionmaker
):
    sa_id, raw_key = await _create_sa(team.owner_client, "revocable-sa")
    await _add_member(team.owner_client, team.project_a["id"], "editor", service_account_id=sa_id)
    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        created = await _create_model(sa_client, "sa-made", team.project_a["id"])
        assert created.status_code == 201
        model_id = created.json()["data"]["id"]
        assert (await sa_client.get(f"{API}/models/{model_id}")).status_code == 200

        access = await team.owner_client.get(f"{API}/auth/models/{model_id}/access")
        assert access.json()["data"] == []  # membership grants access, no ModelAccess entry is created

        membership_id = await _membership_id(team.owner_client, team.project_a["id"], "revocable-sa")
        removed = await team.owner_client.delete(f"{API}/projects/{team.project_a['id']}/members/{membership_id}")
        assert removed.status_code == 204

        assert (await sa_client.get(f"{API}/models/{model_id}")).status_code == 403
        assert (await sa_client.put(f"{API}/models/{model_id}", json={"description": "x"})).status_code == 403


async def test_sa_default_project_fallback_creates_model_access_entry(
    owner_client: AsyncClient, pg_session_factory: async_sessionmaker
):
    sa_id, raw_key = await _create_sa(owner_client, "fallback-sa")
    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        model_id = (await _create_model(sa_client, "fallback-model")).json()["data"]["id"]
        assert (await sa_client.put(f"{API}/models/{model_id}", json={"description": "x"})).status_code == 200

    access = (await owner_client.get(f"{API}/auth/models/{model_id}/access")).json()["data"]
    assert [entry["service_account_id"] for entry in access] == [sa_id]


async def test_sa_viewer_of_default_project_can_still_create_there_via_fallback(
    owner_client: AsyncClient, pg_session_factory: async_sessionmaker
):
    await _create_model(owner_client, "seeds-default-project")
    default_id = await _default_project_id(owner_client)
    sa_id, raw_key = await _create_sa(owner_client, "default-viewer-sa")
    await _add_member(owner_client, default_id, "viewer", service_account_id=sa_id)

    async with await _make_sa_client(pg_session_factory, raw_key) as sa_client:
        created = await _create_model(sa_client, "viewer-sa-default-model")
        assert created.status_code == 201
        model_id = created.json()["data"]["id"]
        assert (await sa_client.put(f"{API}/models/{model_id}", json={"description": "x"})).status_code == 200
        other = await _model_in_project(owner_client, "someone-elses", default_id)
        assert (await sa_client.get(f"{API}/models/{other['id']}")).status_code == 200  # viewer membership
        assert (await sa_client.put(f"{API}/models/{other['id']}", json={"description": "x"})).status_code == 403


async def test_default_project_name_is_reserved(team: Team):
    owner = team.owner_client
    assert (await owner.post(f"{API}/projects", json={"name": "default"})).status_code == 409
    renamed = await team.clients["a-owner"].patch(f"{API}/projects/{team.project_a['id']}", json={"name": "default"})
    assert renamed.status_code == 409
    assert (await owner.patch(f"{API}/projects/{team.project_b['id']}", json={"name": "default"})).status_code == 409

    await _create_model(owner, "creates-default-project")
    default_id = await _default_project_id(owner)
    same_name = await owner.patch(f"{API}/projects/{default_id}", json={"name": "default", "description": "d"})
    assert same_name.status_code == 200  # the default project itself may keep its name


async def test_service_accounts_cannot_be_project_owners(team: Team):
    sa_id, _ = await _create_sa(team.owner_client, "owner-candidate-sa")
    base = f"{API}/projects/{team.project_a['id']}/members"
    for client in (team.owner_client, team.clients["a-owner"]):
        resp = await client.post(base, json={"role": "owner", "service_account_id": sa_id})
        assert resp.status_code == 422
        assert "Service accounts cannot be project owners" in resp.text

    member = await _add_member(team.owner_client, team.project_a["id"], "editor", service_account_id=sa_id)
    promoted = await team.clients["a-owner"].patch(f"{base}/{member['id']}", json={"role": "owner"})
    assert promoted.status_code == 422
    assert "Service accounts cannot be project owners" in promoted.text
    assert (await team.owner_client.patch(f"{base}/{member['id']}", json={"role": "owner"})).status_code == 422


async def test_last_project_owner_cannot_leave_unless_global_owner(team: Team):
    base = f"{API}/projects/{team.project_a['id']}/members"
    owner_client = team.clients["a-owner"]
    own_membership = await _membership_id(team.owner_client, team.project_a["id"], "a-owner")

    assert (await owner_client.delete(f"{base}/{own_membership}")).status_code == 409
    assert (await owner_client.patch(f"{base}/{own_membership}", json={"role": "editor"})).status_code == 409
    assert (await owner_client.patch(f"{base}/{own_membership}", json={"role": "owner"})).status_code == 200

    second = await _add_member(owner_client, team.project_a["id"], "owner", user_id=str(team.users["outsider"].id))
    assert (await owner_client.patch(f"{base}/{own_membership}", json={"role": "editor"})).status_code == 200
    # a-owner is an editor now; the remaining owner is the former outsider
    assert (await team.clients["outsider"].delete(f"{base}/{second['id']}")).status_code == 409

    assert (await team.owner_client.delete(f"{base}/{second['id']}")).status_code == 204  # global owners may
    assert (await team.clients["a-editor"].get(base)).status_code == 403


async def test_deleting_user_or_service_account_removes_memberships(team: Team):
    sa_id, _ = await _create_sa(team.owner_client, "cascade-sa")
    await _add_member(team.owner_client, team.project_a["id"], "viewer", service_account_id=sa_id)
    base = f"{API}/projects/{team.project_a['id']}/members"
    before = {m["name"] for m in (await team.owner_client.get(base)).json()["data"]}
    assert {"a-viewer", "cascade-sa"} <= before

    assert (await team.owner_client.delete(f"{API}/auth/users/{team.users['a-viewer'].id}")).status_code == 204
    assert (await team.owner_client.delete(f"{API}/auth/service-accounts/{sa_id}")).status_code == 204

    after = {m["name"] for m in (await team.owner_client.get(base)).json()["data"]}
    assert after == before - {"a-viewer", "cascade-sa"}


class WriteCases:
    """Write requests against one model version; the order matters (triggering a job locks the schema)."""

    def __init__(self, owner: AsyncClient, model_id: str, version_id: str, job_id: str):
        self.owner = owner
        self.version_id = version_id
        self.job_id = job_id
        self.schema_calls = 0
        self.version_url = f"{API}/models/{model_id}/versions/{version_id}"
        self.requests = {
            "reference-data": self.reference_data,
            "ground-truth": self.ground_truth,
            "version-patch": self.version_patch,
            "threshold-patch": self.threshold_patch,
            "schema-overwrite": self.schema_overwrite,
            "job-patch": self.job_patch,
            "job-trigger": self.job_trigger,
        }

    async def reference_data(self, client: AsyncClient):
        records = [{"inputs": {"age": 20 + i}, "outputs": {"score": 0.5}} for i in range(5)]
        return await client.post(f"{self.version_url}/reference-data", json={"records": records})

    async def ground_truth(self, client: AsyncClient):
        payload = {"model_version_id": self.version_id, "inputs": {"age": 1}, "outputs": {"score": 0.1}}
        inference_id = (await self.owner.post(f"{API}/inferences", json=payload)).json()["data"]["id"]
        return await client.post(f"{API}/ground-truth", json={"inference_id": inference_id, "label": {"score": 1}})

    async def version_patch(self, client: AsyncClient):
        return await client.patch(self.version_url, json={"description": "patched"})

    async def threshold_patch(self, client: AsyncClient):
        fields = (await self.owner.get(self.version_url)).json()["data"]["schema_fields"]
        field_id = next(f["id"] for f in fields if f["direction"] == "input")
        return await client.patch(f"{self.version_url}/fields/{field_id}/threshold", json={"alert_threshold": 0.3})

    async def schema_overwrite(self, client: AsyncClient):
        # Fresh field names per call: re-using existing names collides with the unique constraint
        self.schema_calls += 1
        schema = [
            {"direction": "input", "field_name": f"income{self.schema_calls}", "data_type": "numerical"},
            {"direction": "output", "field_name": f"risk{self.schema_calls}", "data_type": "numerical"},
        ]
        return await client.put(f"{self.version_url}/schema", json=schema)

    async def job_patch(self, client: AsyncClient):
        return await client.patch(f"{API}/jobs/{self.job_id}", json={"name": "renamed-job"})

    async def job_trigger(self, client: AsyncClient):
        return await client.post(f"{API}/jobs/{self.job_id}/trigger")


async def test_write_endpoint_matrix_per_project_role(team: Team):
    model = await _model_in_project(team.owner_client, "matrix-model", team.project_a["id"])
    version = await _create_version(team.owner_client, model["id"])
    jobs = (await team.owner_client.get(f"{API}/models/{model['id']}/versions/{version['id']}/jobs")).json()["data"]
    cases = WriteCases(team.owner_client, model["id"], version["id"], jobs[0]["id"])

    for endpoint, request in cases.requests.items():
        for name in ("a-viewer", "outsider"):
            resp = await request(team.clients[name])
            assert resp.status_code == 403, f"{endpoint} as {name}: {resp.status_code} {resp.text}"
    for endpoint, request in cases.requests.items():
        for name in ("a-editor", "a-owner"):
            resp = await request(team.clients[name])
            assert 200 <= resp.status_code < 300, f"{endpoint} as {name}: {resp.status_code} {resp.text}"
