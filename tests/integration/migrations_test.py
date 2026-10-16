"""Integration tests for explicit migrations and the startup schema check (real PostgreSQL)."""

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
    # alembic's env.py reads DATABASE_URL from the environment, so both must point at the isolated DB
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "cloud_sql_instance", None)

    yield url

    with pg_sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))


def test_check_fails_on_unmigrated_database(isolated_db):
    with pytest.raises(migrate.SchemaNotUpToDateError, match="python -m yaai.server.migrate"):
        migrate.check_schema_up_to_date()


def test_check_passes_after_migrations(isolated_db):
    migrate.run_migrations()

    migrate.check_schema_up_to_date()

    engine = create_engine(settings.database_url_sync)
    try:
        with engine.connect() as conn:
            current, head = migrate.get_migration_status(conn)
    finally:
        engine.dispose()
    assert current == head


def test_check_fails_when_database_is_behind(isolated_db):
    migrate.run_migrations()
    engine = create_engine(settings.database_url_sync)
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = 'outdated_revision'"))
    finally:
        engine.dispose()

    with pytest.raises(migrate.SchemaNotUpToDateError, match="outdated_revision"):
        migrate.check_schema_up_to_date()
