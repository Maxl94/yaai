"""Migration test for projects (revision d8f2b3c4e5a6) on an isolated PostgreSQL database."""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url

from tests.integration.conftest import PG_AVAILABLE

pytestmark = pytest.mark.skipif(not PG_AVAILABLE, reason="Docker not available")

PREVIOUS_REVISION = "c7e1a2b3d4f5"
REVISION = "d8f2b3c4e5a6"
_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "yaai" / "server" / "alembic.ini"


@pytest.fixture
def migration_engine(pg_sync_url: str, pg_sync_engine: Engine) -> Iterator[Engine]:
    """Engine bound to a freshly created database so other tests are unaffected."""
    db_name = f"migration_{uuid.uuid4().hex[:12]}"
    with pg_sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine = create_engine(make_url(pg_sync_url).set(database=db_name))
    yield engine
    engine.dispose()
    with pg_sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE "{db_name}" WITH (FORCE)'))


def _run(engine: Engine, action, revision: str) -> None:
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        action(cfg, revision)


def _upgrade(engine: Engine, revision: str) -> None:
    _run(engine, command.upgrade, revision)


def _downgrade(engine: Engine, revision: str) -> None:
    _run(engine, command.downgrade, revision)


def _seed(engine: Engine) -> dict[str, uuid.UUID]:
    """Insert two models, two users and a service account (with model access) at the previous revision."""
    ids = {name: uuid.uuid4() for name in ("model_a", "model_b", "user_a", "user_b", "sa")}
    with engine.begin() as conn:
        for key, name in (("model_a", "model-a"), ("model_b", "model-b")):
            conn.execute(text("INSERT INTO models (id, name) VALUES (:id, :name)"), {"id": ids[key], "name": name})
        for key, name, role in (("user_a", "a", "OWNER"), ("user_b", "b", "VIEWER")):
            conn.execute(
                text(
                    "INSERT INTO users (id, username, role, auth_provider, is_active) "
                    "VALUES (:id, :name, :role, 'LOCAL', true)"
                ),
                {"id": ids[key], "name": name, "role": role},
            )
        conn.execute(
            text("INSERT INTO service_accounts (id, name, auth_type, is_active) VALUES (:id, 'sa', 'api_key', true)"),
            {"id": ids["sa"]},
        )
        conn.execute(
            text("INSERT INTO model_access (id, model_id, service_account_id) VALUES (:id, :m, :s)"),
            {"id": uuid.uuid4(), "m": ids["model_a"], "s": ids["sa"]},
        )
    return ids


def _unique_constraints(engine: Engine) -> dict[str, list[str]]:
    return {c["name"]: c["column_names"] for c in inspect(engine).get_unique_constraints("models")}


def test_upgrade_moves_models_into_default_project_and_adds_viewers(migration_engine: Engine):
    _upgrade(migration_engine, PREVIOUS_REVISION)
    ids = _seed(migration_engine)

    _upgrade(migration_engine, "head")

    with migration_engine.connect() as conn:
        projects = conn.execute(text("SELECT id, name FROM projects")).all()
        assert [p.name for p in projects] == ["default"]
        default_id = projects[0].id
        assert {r.id for r in conn.execute(text("SELECT id FROM models WHERE project_id = :p"), {"p": default_id})} == {
            ids["model_a"],
            ids["model_b"],
        }
        memberships = conn.execute(
            text("SELECT user_id, service_account_id, role::text AS role FROM project_memberships")
        ).all()
        access = conn.execute(text("SELECT model_id, service_account_id FROM model_access")).all()
    assert {(m.user_id, m.role) for m in memberships} == {(ids["user_a"], "VIEWER"), (ids["user_b"], "VIEWER")}
    assert all(m.service_account_id is None for m in memberships)
    assert [(a.model_id, a.service_account_id) for a in access] == [(ids["model_a"], ids["sa"])]


def test_upgrade_swaps_global_name_uniqueness_for_per_project(migration_engine: Engine):
    _upgrade(migration_engine, PREVIOUS_REVISION)
    _seed(migration_engine)
    assert _unique_constraints(migration_engine) == {"models_name_key": ["name"]}

    _upgrade(migration_engine, "head")

    assert _unique_constraints(migration_engine) == {"uq_model_project_name": ["project_id", "name"]}
    other_project = uuid.uuid4()
    with migration_engine.begin() as conn:
        conn.execute(text("INSERT INTO projects (id, name) VALUES (:id, 'other')"), {"id": other_project})
        conn.execute(
            text("INSERT INTO models (id, name, project_id) VALUES (:id, 'model-a', :p)"),
            {"id": uuid.uuid4(), "p": other_project},
        )
    with pytest.raises(Exception, match="uq_model_project_name"):
        with migration_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO models (id, name, project_id) VALUES (:id, 'model-a', :p)"),
                {"id": uuid.uuid4(), "p": other_project},
            )


def test_upgrade_enforces_membership_and_model_constraints(migration_engine: Engine):
    _upgrade(migration_engine, PREVIOUS_REVISION)
    ids = _seed(migration_engine)
    _upgrade(migration_engine, "head")

    with migration_engine.connect() as conn:
        default_id = conn.execute(text("SELECT id FROM projects")).scalar_one()
    insert = text(
        "INSERT INTO project_memberships (id, project_id, user_id, service_account_id, role) "
        "VALUES (:id, :p, :u, :s, 'EDITOR')"
    )
    with migration_engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4(), "p": default_id, "u": None, "s": ids["sa"]})
    for params, constraint in (
        ({"u": None, "s": ids["sa"]}, "uq_project_memberships_sa"),
        ({"u": ids["user_a"], "s": None}, "uq_project_memberships_user"),
        ({"u": None, "s": None}, "ck_project_memberships_one_principal"),
        ({"u": ids["user_b"], "s": ids["sa"]}, "ck_project_memberships_one_principal"),
    ):
        with pytest.raises(Exception, match=constraint):
            with migration_engine.begin() as conn:
                conn.execute(insert, {"id": uuid.uuid4(), "p": default_id, **params})

    with pytest.raises(Exception, match="fk_models_project_id|models"):
        with migration_engine.begin() as conn:
            conn.execute(text("DELETE FROM projects WHERE id = :p"), {"p": default_id})  # RESTRICT while models exist
    with pytest.raises(Exception, match="null value"):
        with migration_engine.begin() as conn:
            conn.execute(text("INSERT INTO models (id, name) VALUES (:id, 'orphan')"), {"id": uuid.uuid4()})


def test_downgrade_restores_global_unique_name_and_drops_projects(migration_engine: Engine):
    _upgrade(migration_engine, PREVIOUS_REVISION)
    ids = _seed(migration_engine)
    _upgrade(migration_engine, "head")

    _downgrade(migration_engine, PREVIOUS_REVISION)

    inspector = inspect(migration_engine)
    assert {"projects", "project_memberships"}.isdisjoint(inspector.get_table_names())
    assert "project_id" not in {c["name"] for c in inspector.get_columns("models")}
    assert _unique_constraints(migration_engine) == {"models_name_key": ["name"]}
    with migration_engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS_REVISION
        assert {r.id for r in conn.execute(text("SELECT id FROM models"))} == {ids["model_a"], ids["model_b"]}
        assert conn.execute(text("SELECT count(*) FROM pg_type WHERE typname = 'projectrole'")).scalar_one() == 0

    _upgrade(migration_engine, "head")
    assert "projects" in inspect(migration_engine).get_table_names()


def test_downgrade_fails_clearly_when_model_names_clash_across_projects(migration_engine: Engine):
    _upgrade(migration_engine, PREVIOUS_REVISION)
    _seed(migration_engine)
    _upgrade(migration_engine, "head")
    other_project = uuid.uuid4()
    with migration_engine.begin() as conn:
        conn.execute(text("INSERT INTO projects (id, name) VALUES (:id, 'other')"), {"id": other_project})
        conn.execute(
            text("INSERT INTO models (id, name, project_id) VALUES (:id, 'model-a', :p)"),
            {"id": uuid.uuid4(), "p": other_project},
        )

    with pytest.raises(RuntimeError, match="model-a"):
        _downgrade(migration_engine, PREVIOUS_REVISION)

    with migration_engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
