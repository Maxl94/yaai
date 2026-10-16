"""Permission matrix for project-based model access (SQLite, real queries)."""

import uuid

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.auth.config import AuthConfig, JWTConfig
from yaai.server.auth.dependencies import (
    CurrentIdentity,
    check_model_read_access,
    check_model_write_access,
    get_accessible_model_ids,
    get_project_role,
    get_project_role_for_model,
    require_project_admin,
    set_auth_config,
)
from yaai.server.models.auth import AuthProvider, ModelAccess, ServiceAccount, User, UserRole
from yaai.server.models.model import Model
from yaai.server.models.project import Project, ProjectMembership, ProjectRole


@pytest.fixture(autouse=True)
def auth_enabled():
    set_auth_config(AuthConfig(enabled=True, jwt=JWTConfig(secret=SecretStr("project-permissions-test-secret!!"))))
    yield
    set_auth_config(AuthConfig(enabled=False))


class World:
    """Two projects (A, B) with one model each and one principal per role."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self) -> "World":
        db = self.db
        self.project_a, self.project_b = Project(name="A"), Project(name="B")
        db.add_all([self.project_a, self.project_b])
        await db.flush()
        self.model_a = Model(name="m", project_id=self.project_a.id)
        self.model_b = Model(name="m", project_id=self.project_b.id)
        self.users = {
            name: User(username=name, role=role, auth_provider=AuthProvider.LOCAL)
            for name, role in (
                ("global_owner", UserRole.OWNER),
                ("project_owner", UserRole.VIEWER),
                ("editor", UserRole.VIEWER),
                ("viewer", UserRole.VIEWER),
                ("outsider", UserRole.VIEWER),
            )
        }
        self.sas = {
            name: ServiceAccount(name=name, auth_type="api_key") for name in ("acl", "editor", "viewer", "none")
        }
        db.add_all([self.model_a, self.model_b, *self.users.values(), *self.sas.values()])
        await db.flush()
        for name, role in (
            ("project_owner", ProjectRole.OWNER),
            ("editor", ProjectRole.EDITOR),
            ("viewer", ProjectRole.VIEWER),
        ):
            db.add(ProjectMembership(project_id=self.project_a.id, user_id=self.users[name].id, role=role))
        for name, role in (("editor", ProjectRole.EDITOR), ("viewer", ProjectRole.VIEWER)):
            db.add(ProjectMembership(project_id=self.project_a.id, service_account_id=self.sas[name].id, role=role))
        db.add(ModelAccess(model_id=self.model_a.id, service_account_id=self.sas["acl"].id))
        await db.commit()
        return self

    def user(self, name: str) -> CurrentIdentity:
        user = self.users[name]
        return CurrentIdentity(user_id=str(user.id), role=user.role, identity_type="user", username=name)

    def sa(self, name: str) -> CurrentIdentity:
        sa_id = str(self.sas[name].id)
        return CurrentIdentity(user_id=sa_id, role=UserRole.VIEWER, identity_type="api_key", service_account_id=sa_id)


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    return await World(db_session).build()


async def _allowed(check, model_id: uuid.UUID, identity: CurrentIdentity, db: AsyncSession) -> bool:
    try:
        await check(model_id, identity, db)
    except HTTPException as exc:
        assert exc.status_code == 403
        return False
    return True


# principal -> (can read model A, can write model A); nobody except the global owner touches model B
MATRIX = [
    ("user", "global_owner", True, True),
    ("user", "project_owner", True, True),
    ("user", "editor", True, True),
    ("user", "viewer", True, False),
    ("user", "outsider", False, False),
    ("sa", "acl", True, True),
    ("sa", "editor", True, True),
    ("sa", "viewer", True, False),
    ("sa", "none", False, False),
]


@pytest.mark.parametrize(("kind", "name", "can_read", "can_write"), MATRIX)
async def test_model_access_matrix(world: World, kind: str, name: str, can_read: bool, can_write: bool):
    identity = world.user(name) if kind == "user" else world.sa(name)
    db = world.db

    assert await _allowed(check_model_read_access, world.model_a.id, identity, db) is can_read
    assert await _allowed(check_model_write_access, world.model_a.id, identity, db) is can_write

    other_project_access = identity.is_owner
    assert await _allowed(check_model_read_access, world.model_b.id, identity, db) is other_project_access
    assert await _allowed(check_model_write_access, world.model_b.id, identity, db) is other_project_access


async def test_auth_disabled_grants_everything(world: World):
    set_auth_config(AuthConfig(enabled=False))
    identity = world.user("outsider")

    await check_model_read_access(world.model_b.id, identity, world.db)
    await check_model_write_access(world.model_b.id, identity, world.db)
    assert await get_accessible_model_ids(identity, world.db) is None
    assert await get_project_role(identity, world.project_b.id, world.db) == ProjectRole.OWNER


async def test_unknown_model_is_404_for_non_owners(world: World):
    with pytest.raises(HTTPException) as exc_info:
        await check_model_read_access(uuid.uuid4(), world.user("viewer"), world.db)
    assert exc_info.value.status_code == 404


async def test_project_role_for_model(world: World):
    db = world.db
    assert await get_project_role_for_model(world.user("editor"), world.model_a.id, db) == ProjectRole.EDITOR
    assert await get_project_role_for_model(world.user("editor"), world.model_b.id, db) is None
    assert await get_project_role_for_model(world.user("global_owner"), world.model_b.id, db) == ProjectRole.OWNER
    assert await get_project_role_for_model(world.sa("acl"), world.model_a.id, db) is None


async def _materialize(world: World, identity) -> list | None:
    query = await get_accessible_model_ids(identity, world.db)
    if query is None:
        return None
    return list((await world.db.execute(query)).scalars().all())


@pytest.mark.parametrize(
    ("kind", "name", "expected"),
    [
        ("user", "global_owner", None),
        ("user", "project_owner", ["a"]),
        ("user", "viewer", ["a"]),
        ("user", "outsider", []),
        ("sa", "acl", ["a"]),
        ("sa", "editor", ["a"]),
        ("sa", "none", []),
    ],
)
async def test_accessible_model_ids(world: World, kind: str, name: str, expected: list[str] | None):
    identity = world.user(name) if kind == "user" else world.sa(name)
    ids = await _materialize(world, identity)
    assert ids == (None if expected is None else [world.model_a.id for _ in expected])


async def test_service_account_gets_union_of_acl_and_project_models(world: World):
    other = Model(name="other", project_id=world.project_b.id)
    world.db.add(other)
    await world.db.flush()
    world.db.add(ModelAccess(model_id=other.id, service_account_id=world.sas["editor"].id))
    await world.db.commit()

    ids = await _materialize(world, world.sa("editor"))

    assert sorted(ids) == sorted([world.model_a.id, other.id])


@pytest.mark.parametrize(
    ("kind", "name", "is_admin"),
    [
        ("user", "global_owner", True),
        ("user", "project_owner", True),
        ("user", "editor", False),
        ("user", "viewer", False),
        ("user", "outsider", False),
        ("sa", "editor", False),
    ],
)
async def test_require_project_admin(world: World, kind: str, name: str, is_admin: bool):
    identity = world.user(name) if kind == "user" else world.sa(name)
    try:
        await require_project_admin(world.project_a.id, identity, world.db)
    except HTTPException as exc:
        assert exc.status_code == 403
        assert not is_admin
    else:
        assert is_admin


async def test_project_owner_is_not_admin_of_other_project(world: World):
    with pytest.raises(HTTPException) as exc_info:
        await require_project_admin(world.project_b.id, world.user("project_owner"), world.db)
    assert exc_info.value.status_code == 403


async def test_require_project_admin_unknown_project_is_404(world: World):
    with pytest.raises(HTTPException) as exc_info:
        await require_project_admin(uuid.uuid4(), world.user("project_owner"), world.db)
    assert exc_info.value.status_code == 404
