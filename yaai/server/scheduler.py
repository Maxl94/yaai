from __future__ import annotations

import logging
import os
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from yaai.server.models.job import JobConfig

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def scheduler_enabled() -> bool:
    """Return whether this instance runs the scheduler (SCHEDULER_ENABLED, default true)."""
    return os.environ.get("SCHEDULER_ENABLED", "true").lower() not in ("false", "0", "no")


def job_lock_key(job_config_id: uuid.UUID) -> int:
    """Derive a deterministic signed 64-bit advisory lock key from a job UUID."""
    return int.from_bytes(job_config_id.bytes[:8], "big", signed=True)


async def _try_acquire_job_lock(conn: AsyncConnection, job_config_id: uuid.UUID) -> bool:
    """Try to take a transaction-level advisory lock for a job on an open transaction.

    The lock is released automatically when the transaction ends, including when the process
    crashes or the connection drops, so a dead instance can never leave a job locked forever.
    Non-PostgreSQL dialects (SQLite in tests) have no advisory locks and always succeed.
    """
    if conn.dialect.name != "postgresql":
        return True
    result = await conn.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": job_lock_key(job_config_id)})
    return bool(result.scalar())


async def _execute_scheduled_job(job_config_id: str) -> None:
    """Called by APScheduler when a cron trigger fires.

    With several instances every instance fires the same cron trigger. A dedicated connection holds
    an advisory lock for the whole execution so only one instance runs the job; the others skip.
    """
    from yaai.server import database  # noqa: PLC0415
    from yaai.server.services.drift_service import DriftService  # noqa: PLC0415

    job_uuid = uuid.UUID(job_config_id)
    try:
        async with database.engine.connect() as lock_conn, lock_conn.begin():
            if not await _try_acquire_job_lock(lock_conn, job_uuid):
                logger.info("Scheduled job %s is already running on another instance; skipping", job_config_id)
                return
            async with database.async_session() as db:
                run = await DriftService(db).execute_job(job_uuid)
            logger.info("Scheduled job %s completed with status: %s", job_config_id, run.status)
    except Exception:
        logger.exception("Scheduled job %s failed", job_config_id)


async def load_active_jobs(db: AsyncSession) -> int:
    """Load all active job configs from the database and register them with the scheduler."""
    result = await db.execute(
        select(JobConfig).where(JobConfig.is_active == True)  # noqa: E712
    )
    jobs = result.scalars().all()

    count = 0
    for job in jobs:
        register_job(job)
        count += 1

    logger.info("Loaded %d active jobs into scheduler", count)
    return count


def register_job(job_config: JobConfig) -> None:
    """Add or replace a job in the scheduler."""
    job_id = str(job_config.id)

    # Remove existing job if present
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if not job_config.is_active:
        return

    scheduler.add_job(
        _execute_scheduled_job,
        CronTrigger.from_crontab(job_config.schedule),
        args=[job_id],
        id=job_id,
        name=job_config.name,
        max_instances=1,
        replace_existing=True,
    )
    logger.info("Registered job %s: %s (%s)", job_id, job_config.name, job_config.schedule)


def unregister_job(job_id: str) -> None:
    """Remove a job from the scheduler."""
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Unregistered job %s", job_id)
