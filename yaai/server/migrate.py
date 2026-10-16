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
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Connection, Engine, create_engine

from yaai.server.config import settings

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_SERVER_DIR = Path(__file__).resolve().parent


class SchemaNotUpToDateError(RuntimeError):
    """Raised when the database schema is empty or behind the latest Alembic revision."""


class SchemaAheadError(RuntimeError):
    """Raised when the database is at a revision this code does not know (migrated by a newer version)."""


@dataclass(frozen=True)
class MigrationStatus:
    """Database revision compared to the revisions shipped with this code.

    Attributes:
        current: Revision stored in the database, None for an unmigrated database.
        head: Latest revision shipped with this code.
        current_is_known: False if the database revision is not part of this code's migration scripts.
    """

    current: str | None
    head: str | None
    current_is_known: bool

    @property
    def is_up_to_date(self) -> bool:
        return self.current == self.head

    @property
    def is_ahead(self) -> bool:
        return self.current is not None and not self.current_is_known


def _alembic_config() -> AlembicConfig:
    return AlembicConfig(str(_SERVER_DIR / "alembic.ini"))


@contextmanager
def _sync_engine() -> Iterator[Engine]:
    """Yield a sync engine (standalone Cloud SQL connector if configured) and release it afterwards."""
    if settings.cloud_sql_instance:
        from yaai.server.cloud_sql import CloudSQLConnector  # noqa: PLC0415

        with CloudSQLConnector.sync_engine() as engine:
            yield engine
        return

    engine = create_engine(settings.database_url_sync)
    try:
        yield engine
    finally:
        engine.dispose()


def get_migration_status(connection: Connection) -> MigrationStatus:
    """Compare the database revision with the latest revision shipped with the code.

    Args:
        connection: An open sync connection to the application database.

    Returns:
        The current revision, the head revision and whether the current revision is known to this code.

    Raises:
        CommandError: If the migration scripts contain multiple heads.
    """
    script = ScriptDirectory.from_config(_alembic_config())
    head = script.get_current_head()
    current = MigrationContext.configure(connection).get_current_revision()
    try:
        if current is not None:
            script.get_revision(current)
    except CommandError:
        return MigrationStatus(current, head, current_is_known=False)
    return MigrationStatus(current, head, current_is_known=True)


def _ahead_message(status: MigrationStatus) -> str:
    return (
        f"database schema revision {status.current} is newer than this application (head {status.head}); "
        "migrations must be backward compatible (expand/contract) for older versions to keep running"
    )


def run_migrations() -> None:
    """Upgrade the database schema to the latest Alembic revision.

    Raises:
        SchemaAheadError: If the database was already migrated by a newer application version.
    """
    alembic_cfg = _alembic_config()
    if settings.cloud_sql_instance:
        logger.info("Running migrations via Cloud SQL connector ...")

    with _sync_engine() as engine, engine.begin() as connection:
        status = get_migration_status(connection)
        if status.is_ahead:
            raise SchemaAheadError(
                f"Cannot migrate: {_ahead_message(status)}. Run the migration with the newer application image."
            )
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")

    logger.info("Migrations complete.")


def check_schema_up_to_date() -> None:
    """Verify that the database schema is not behind the latest Alembic revision.

    A database that is ahead of this code (e.g. after rolling back to an older image) only
    logs a warning so that a rollback does not require downgrading the database first.

    Raises:
        SchemaNotUpToDateError: If the database is unmigrated or behind the code's head revision.
    """
    with _sync_engine() as engine, engine.connect() as connection:
        status = get_migration_status(connection)

    if status.is_up_to_date:
        return
    if status.is_ahead:
        logger.warning("Continuing startup: %s", _ahead_message(status))
        return
    raise SchemaNotUpToDateError(
        f"Database schema is not up to date (current revision: {status.current or 'none'}, "
        f"expected: {status.head}). Run `python -m yaai.server.migrate` before starting the server."
    )


def main() -> None:
    """Run all pending migrations and exit non-zero on failure."""
    try:
        run_migrations()
    except SchemaAheadError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except Exception:
        logger.exception("Failed to apply database migrations")
        sys.exit(1)


if __name__ == "__main__":
    main()
