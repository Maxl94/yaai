"""Standalone migration script — runs Alembic migrations, then exits.

Designed to run as a separate process before uvicorn starts, avoiding
event loop conflicts with the Cloud SQL async Connector.

Usage:
    python -m yaai.server.migrate
"""

import logging
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

from yaai.server.config import settings

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_SERVER_DIR = Path(__file__).resolve().parent


def run_migrations() -> None:
    alembic_cfg = AlembicConfig(str(_SERVER_DIR / "alembic.ini"))

    if settings.cloud_sql_instance:
        from yaai.server.cloud_sql import CloudSQLConnector

        logger.info("Running migrations via Cloud SQL connector ...")
        engine = CloudSQLConnector.create_sync_engine()
        with engine.begin() as connection:
            alembic_cfg.attributes["connection"] = connection
            command.upgrade(alembic_cfg, "head")
    else:
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url_sync)
        command.upgrade(alembic_cfg, "head")

    logger.info("Migrations complete.")


if __name__ == "__main__":
    if os.environ.get("AUTO_MIGRATE", "true").lower() not in ("true", "1", "yes"):
        logger.info("AUTO_MIGRATE is disabled — skipping.")
        sys.exit(0)
    run_migrations()
