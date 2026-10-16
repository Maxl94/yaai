"""Migration test for notification_reads (revision c7e1a2b3d4f5) on an isolated PostgreSQL database."""

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

PREVIOUS_REVISION = "b4d9e2f1a8c3"
REVISION = "c7e1a2b3d4f5"
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


def _upgrade(engine: Engine, revision: str) -> None:
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def _downgrade(engine: Engine, revision: str) -> None:
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, revision)


def _seed(engine: Engine) -> dict[str, uuid.UUID]:
    """Insert two users, a service account and notifications (one read, one unread) at the previous revision."""
    ids = {name: uuid.uuid4() for name in ("model", "version", "user_a", "user_b", "sa", "read", "unread")}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO models (id, name) VALUES (:id, 'm')"), {"id": ids["model"]})
        conn.execute(
            text("INSERT INTO model_versions (id, model_id, version, is_active) VALUES (:id, :m, 'v1', true)"),
            {"id": ids["version"], "m": ids["model"]},
        )
        for key, name in (("user_a", "a"), ("user_b", "b")):
            conn.execute(
                text(
                    "INSERT INTO users (id, username, role, auth_provider, is_active) "
                    "VALUES (:id, :name, 'VIEWER', 'LOCAL', true)"
                ),
                {"id": ids[key], "name": name},
            )
        conn.execute(
            text("INSERT INTO service_accounts (id, name, auth_type, is_active) VALUES (:id, 'sa', 'api_key', true)"),
            {"id": ids["sa"]},
        )
        for key, is_read in (("read", True), ("unread", False)):
            conn.execute(
                text(
                    "INSERT INTO notifications (id, model_version_id, severity, message, is_read) "
                    "VALUES (:id, :v, 'WARNING', 'drift', :is_read)"
                ),
                {"id": ids[key], "v": ids["version"], "is_read": is_read},
            )
    return ids


def test_upgrade_backfills_reads_for_existing_users(migration_engine: Engine):
    _upgrade(migration_engine, PREVIOUS_REVISION)
    ids = _seed(migration_engine)

    _upgrade(migration_engine, "head")

    with migration_engine.connect() as conn:
        rows = conn.execute(text("SELECT notification_id, user_id, service_account_id FROM notification_reads")).all()
        is_read = dict(conn.execute(text("SELECT id, is_read FROM notifications")).all())
    assert {(r.notification_id, r.user_id) for r in rows} == {
        (ids["read"], ids["user_a"]),
        (ids["read"], ids["user_b"]),
    }
    assert all(r.service_account_id is None for r in rows)
    assert is_read == {ids["read"]: True, ids["unread"]: False}


def test_upgrade_enforces_constraints(migration_engine: Engine):
    _upgrade(migration_engine, PREVIOUS_REVISION)
    ids = _seed(migration_engine)
    _upgrade(migration_engine, "head")

    insert = text(
        "INSERT INTO notification_reads (id, notification_id, user_id, service_account_id) VALUES (:id, :n, :u, :s)"
    )
    with migration_engine.begin() as conn:
        conn.execute(insert, {"id": uuid.uuid4(), "n": ids["unread"], "u": None, "s": ids["sa"]})
    for params in (
        {"n": ids["unread"], "u": None, "s": ids["sa"]},  # duplicate SA read
        {"n": ids["read"], "u": ids["user_a"], "s": None},  # duplicate user read (backfilled)
        {"n": ids["unread"], "u": None, "s": None},  # no reader
        {"n": ids["unread"], "u": ids["user_a"], "s": ids["sa"]},  # two readers
    ):
        with pytest.raises(Exception, match="notification_reads"):
            with migration_engine.begin() as conn:
                conn.execute(insert, {"id": uuid.uuid4(), **params})


def test_downgrade_drops_table_and_keeps_notifications(migration_engine: Engine):
    _upgrade(migration_engine, PREVIOUS_REVISION)
    ids = _seed(migration_engine)
    _upgrade(migration_engine, "head")
    assert "notification_reads" in inspect(migration_engine).get_table_names()

    _downgrade(migration_engine, PREVIOUS_REVISION)

    assert "notification_reads" not in inspect(migration_engine).get_table_names()
    with migration_engine.connect() as conn:
        is_read = dict(conn.execute(text("SELECT id, is_read FROM notifications")).all())
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS_REVISION
    assert is_read == {ids["read"]: True, ids["unread"]: False}

    _upgrade(migration_engine, "head")
    assert "notification_reads" in inspect(migration_engine).get_table_names()
