"""Alembic environment bound to the YAAI settings (``DATABASE_URL``/``.env`` or the Cloud SQL connector)."""

from logging.config import fileConfig

from alembic import context

from yaai.server.config import settings
from yaai.server.database import Base
from yaai.server.migrate import sync_engine

# Import all models so they register with Base.metadata
from yaai.server.models import auth, inference, job, model, project  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url_sync, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests pass their own connection; otherwise connect to the configured database
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_migrations(connection)
        return

    with sync_engine() as engine, engine.connect() as connection:
        _run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
