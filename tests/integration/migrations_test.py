"""Integration tests for explicit migrations and the startup schema check (real PostgreSQL)."""

import logging
import uuid

import pytest
from sqlalchemy import create_engine, text

from yaai.server import migrate
from yaai.server.config import settings


@pytest.fixture
def isolated_db(pg_container, pg_sync_engine, monkeypatch):
    """Create an empty database in the shared container and point the settings at it."""
    db_name = f"migrate_{uuid.uuid4().hex[:8]}"
    with pg_sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    url = f"postgresql+asyncpg://{pg_container.username}:{pg_container.password}@{host}:{port}/{db_name}"
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "cloud_sql_instance", None)

    yield url

    with pg_sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))


def _status() -> migrate.MigrationStatus:
    with migrate.sync_engine() as engine, engine.connect() as conn:
        return migrate.get_migration_status(conn)


def test_check_fails_on_unmigrated_database(isolated_db):
    with pytest.raises(migrate.SchemaNotUpToDateError, match="python -m yaai.server.migrate"):
        migrate.check_schema_up_to_date()


def test_check_passes_after_migrations(isolated_db):
    migrate.main([])

    migrate.check_schema_up_to_date()
    assert _status().is_up_to_date


def test_check_fails_when_database_is_behind(isolated_db):
    migrate.main(["upgrade", "7f3c318ce50f"])

    with pytest.raises(migrate.SchemaNotUpToDateError, match="7f3c318ce50f"):
        migrate.check_schema_up_to_date()


def test_main_upgrades_database_that_is_behind(isolated_db):
    migrate.main(["upgrade", "7f3c318ce50f"])

    migrate.main([])

    migrate.check_schema_up_to_date()


def _stamp_unknown_revision() -> None:
    engine = create_engine(settings.database_url_sync)
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = 'future_revision'"))
    finally:
        engine.dispose()


def test_check_warns_and_continues_when_database_is_ahead(isolated_db):
    migrate.main([])
    _stamp_unknown_revision()
    records: list[logging.LogRecord] = []
    handler = logging.Handler(level=logging.WARNING)
    handler.emit = records.append  # alembic's fileConfig drops root handlers, so caplog cannot be used here
    migrate.logger.addHandler(handler)
    try:
        migrate.check_schema_up_to_date()
    finally:
        migrate.logger.removeHandler(handler)

    messages = [record.getMessage() for record in records]
    assert any("future_revision" in m and "newer than this application" in m for m in messages)


def test_main_fails_when_database_is_ahead(isolated_db):
    migrate.main([])
    _stamp_unknown_revision()

    with pytest.raises(SystemExit) as exc_info:
        migrate.main([])

    assert exc_info.value.code != 0


def test_main_downgrades_one_revision(isolated_db):
    migrate.main([])
    head = _status().head

    migrate.main(["downgrade", "-1"])

    status = _status()
    assert status.current is not None
    assert status.current != head


def test_all_migrations_downgrade_to_base_and_upgrade_again(isolated_db):
    migrate.main([])

    migrate.main(["downgrade", "base"])
    assert _status().current is None

    migrate.main([])
    assert _status().is_up_to_date
