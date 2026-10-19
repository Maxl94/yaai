"""Alembic CLI pass-through bound to the configured YAAI database.

Database migrations are never applied automatically when the server starts.
Run this module (locally, as a Docker Compose service or as a Cloud Run Job)
before starting the server. All arguments are passed to the Alembic CLI with the
packaged ``alembic.ini``; the database (``DATABASE_URL`` or the Cloud SQL
connector) is resolved from the YAAI settings in ``alembic/env.py``.

Usage:
    python -m yaai.server.migrate                  # upgrade head (default)
    python -m yaai.server.migrate downgrade -1
    python -m yaai.server.migrate current
    python -m yaai.server.migrate --help
"""

import logging
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import alembic.config
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

_ALEMBIC_INI = Path(__file__).resolve().parent / "alembic.ini"


class SchemaNotUpToDateError(RuntimeError):
    """Raised when the database schema is empty or behind the latest Alembic revision."""


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
    return AlembicConfig(str(_ALEMBIC_INI))


@contextmanager
def sync_engine() -> Iterator[Engine]:
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


def check_schema_up_to_date() -> None:
    """Verify that the database schema is not behind the latest Alembic revision.

    A database that is ahead of this code (e.g. after rolling back to an older image) only
    logs a warning so that a rollback does not require downgrading the database first.

    Raises:
        SchemaNotUpToDateError: If the database is unmigrated or behind the code's head revision.
    """
    with sync_engine() as engine, engine.connect() as connection:
        status = get_migration_status(connection)

    if status.is_up_to_date:
        return
    if status.is_ahead:
        logger.warning(
            "Continuing startup: database schema revision %s is newer than this application (head %s); "
            "migrations must be backward compatible (expand/contract) for older versions to keep running",
            status.current,
            status.head,
        )
        return
    raise SchemaNotUpToDateError(
        f"Database schema is not up to date (current revision: {status.current or 'none'}, "
        f"expected: {status.head}). Run `python -m yaai.server.migrate` before starting the server."
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Run an Alembic CLI command against the configured database (``upgrade head`` without arguments)."""
    args = list(sys.argv[1:] if argv is None else argv) or ["upgrade", "head"]
    alembic.config.main(["-c", str(_ALEMBIC_INI), *args], prog="python -m yaai.server.migrate")


if __name__ == "__main__":
    main()
