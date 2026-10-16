"""Standalone migration script — runs Alembic migrations, then exits.

Database migrations are never applied automatically when the server starts.
Run this script (locally, as a Docker Compose service or as a Cloud Run Job)
before starting the server. It also avoids event loop conflicts with the
Cloud SQL async Connector.

Usage:
    python -m yaai.server.migrate
"""

import logging
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, create_engine

from yaai.server.config import settings

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_SERVER_DIR = Path(__file__).resolve().parent


class SchemaNotUpToDateError(RuntimeError):
    """Raised when the database schema is not at the latest Alembic revision."""


def _alembic_config() -> AlembicConfig:
    return AlembicConfig(str(_SERVER_DIR / "alembic.ini"))


def _create_sync_engine() -> Engine:
    """Create a sync engine, using a standalone Cloud SQL connector if configured."""
    if settings.cloud_sql_instance:
        from yaai.server.cloud_sql import CloudSQLConnector  # noqa: PLC0415

        return CloudSQLConnector.create_sync_engine()
    return create_engine(settings.database_url_sync)


def run_migrations() -> None:
    """Upgrade the database schema to the latest Alembic revision."""
    alembic_cfg = _alembic_config()

    if settings.cloud_sql_instance:
        logger.info("Running migrations via Cloud SQL connector ...")
        engine = _create_sync_engine()
        try:
            with engine.begin() as connection:
                alembic_cfg.attributes["connection"] = connection
                command.upgrade(alembic_cfg, "head")
        finally:
            engine.dispose()
    else:
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url_sync)
        command.upgrade(alembic_cfg, "head")

    logger.info("Migrations complete.")


def get_migration_status(connection: Connection) -> tuple[str | None, str | None]:
    """Return the current database revision and the latest revision shipped with the code.

    Args:
        connection: An open sync connection to the application database.

    Returns:
        Tuple of (current revision or None for an unmigrated database, head revision).
    """
    current = MigrationContext.configure(connection).get_current_revision()
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    return current, head


def check_schema_up_to_date() -> None:
    """Verify that the database schema is at the latest Alembic revision.

    Raises:
        SchemaNotUpToDateError: If the database is unmigrated or behind the code's head revision.
    """
    engine = _create_sync_engine()
    try:
        with engine.connect() as connection:
            current, head = get_migration_status(connection)
    finally:
        engine.dispose()

    if current != head:
        raise SchemaNotUpToDateError(
            f"Database schema is not up to date (current revision: {current or 'none'}, expected: {head}). "
            "Run `python -m yaai.server.migrate` before starting the server."
        )


def main() -> None:
    """Run all pending migrations and exit non-zero on failure."""
    try:
        run_migrations()
    except Exception:
        logger.exception("Failed to apply database migrations")
        sys.exit(1)


if __name__ == "__main__":
    main()
