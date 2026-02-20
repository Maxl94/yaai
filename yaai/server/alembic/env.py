import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from yaai.server.database import Base

# Import all models so they register with Base.metadata
from yaai.server.models import auth, inference, job, model  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Derive sync URL from DATABASE_URL (strip +asyncpg driver) if set
_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    import re

    config.set_main_option("sqlalchemy.url", re.sub(r"\+asyncpg", "", _db_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # If a connection was provided (e.g. from Cloud SQL connector), use it directly
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
