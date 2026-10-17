"""Startup and shutdown steps shared by the API lifespan and the headless worker."""

import asyncio
import logging

from yaai.server import database
from yaai.server.config import settings
from yaai.server.migrate import SchemaNotUpToDateError, check_schema_up_to_date
from yaai.server.scheduler import load_active_jobs, scheduler, start_job_sync

logger = logging.getLogger(__name__)


async def init_database():
    """Fail fast if the schema is behind, then set up the Cloud SQL connector if configured.

    Migrations are never applied here.

    Returns:
        The started ``CloudSQLConnector``, or None when ``DATABASE_URL`` is used.

    Raises:
        SchemaNotUpToDateError: If the database is unmigrated or behind this code.
    """
    try:
        await asyncio.to_thread(check_schema_up_to_date)
    except SchemaNotUpToDateError as exc:
        logger.error("%s", exc)
        raise

    if not settings.cloud_sql_instance:
        logger.info("Using DATABASE_URL (no Cloud SQL connector).")
        return None

    from yaai.server.cloud_sql import CloudSQLConnector  # noqa: PLC0415

    cloud_sql = CloudSQLConnector()
    await cloud_sql.startup()
    database.init_engine(async_creator=cloud_sql.async_creator)
    logger.info("Cloud SQL connector ready.")
    return cloud_sql


async def start_scheduler() -> None:
    """Register all active jobs and the periodic reconciliation, then start the scheduler."""
    logger.info("Loading active jobs ...")
    async with database.async_session() as db:
        await load_active_jobs(db)
    start_job_sync()
    scheduler.start()


async def shutdown(cloud_sql) -> None:
    """Stop the scheduler (if running) and the Cloud SQL connector (if any)."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
    if cloud_sql:
        await cloud_sql.shutdown()
