from __future__ import annotations

import asyncio
import logging
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from yaai.server.config import env_bool
from yaai.server.models.job import JobConfig

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

SYNC_JOB_ID = "__scheduler_sync__"
SYNC_INTERVAL_SECONDS = 60


def scheduler_enabled() -> bool:
    """Return whether this instance runs the scheduler (SCHEDULER_ENABLED, default true)."""
    return env_bool("SCHEDULER_ENABLED", True)


def job_lock_key(job_config_id: uuid.UUID) -> int:
    """Derive a deterministic signed 64-bit advisory lock key from a job UUID."""
    return int.from_bytes(job_config_id.bytes[:8], "big", signed=True)


async def _try_acquire_job_lock(conn: AsyncConnection, job_config_id: uuid.UUID) -> bool:
    """Try to take a session-level advisory lock for a job on ``conn`` and commit.

    A session-level lock survives the commits made while the job runs. It is released by
    ``_release_job_lock`` or when the connection drops, so a dead instance never leaves a job locked.
    Non-PostgreSQL dialects (SQLite in tests) have no advisory locks and always succeed.
    """
    if conn.dialect.name != "postgresql":
        return True
    result = await conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": job_lock_key(job_config_id)})
    acquired = bool(result.scalar())
    await conn.commit()  # leave no open transaction so the job session can manage its own
    return acquired


async def _release_job_lock(conn: AsyncConnection, job_config_id: uuid.UUID) -> None:
    """Release the session-level advisory lock; invalidate the connection if that is not possible.

    Invalidating closes the DB connection, which releases the lock server-side, so a pooled
    connection can never be handed out while still holding the lock.
    """
    if conn.dialect.name != "postgresql":
        return
    try:
        await conn.rollback()
        await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": job_lock_key(job_config_id)})
        await conn.commit()
    except BaseException as exc:
        logger.exception("Could not release advisory lock for job %s; discarding its connection", job_config_id)
        await asyncio.shield(conn.invalidate())
        if not isinstance(exc, Exception):
            raise  # keep task cancellation intact


async def _execute_scheduled_job(job_config_id: str) -> None:
    """Called by APScheduler when a cron trigger fires.

    With several instances every instance fires the same cron trigger. A session-level advisory lock
    on one dedicated connection is held for the whole execution so only one instance runs the job;
    the others skip. The job runs on that same connection, so it needs exactly one pooled connection.
    """
    from yaai.server import database  # noqa: PLC0415
    from yaai.server.services.drift_service import DriftService  # noqa: PLC0415

    job_uuid = uuid.UUID(job_config_id)
    try:
        async with database.engine.connect() as conn:
            if not await _try_acquire_job_lock(conn, job_uuid):
                logger.info("Scheduled job %s is already running on another instance; skipping", job_config_id)
                return
            try:
                async with AsyncSession(bind=conn, expire_on_commit=False) as db:
                    run = await DriftService(db).execute_job(job_uuid)
            finally:
                await _release_job_lock(conn, job_uuid)
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


def _is_registered_current(job_config: JobConfig) -> bool:
    """Return whether the scheduler holds this job with the same schedule and name."""
    existing = scheduler.get_job(str(job_config.id))
    return (
        existing is not None
        and existing.name == job_config.name
        and str(existing.trigger) == str(CronTrigger.from_crontab(job_config.schedule))
    )


async def sync_jobs(db: AsyncSession) -> None:
    """Reconcile the scheduler with the active job configs in the database.

    Adds new jobs, re-registers jobs whose schedule or name changed and removes jobs that were
    deactivated or deleted. This propagates API changes made on other instances. A job with an
    invalid schedule is logged and skipped so it cannot block the others.
    """
    result = await db.execute(
        select(JobConfig).where(JobConfig.is_active == True)  # noqa: E712
    )
    active_ids = set()
    for job in result.scalars().all():
        active_ids.add(str(job.id))
        try:
            if not _is_registered_current(job):
                register_job(job)
        except ValueError:
            logger.exception("Skipping job %s with invalid schedule %r", job.id, job.schedule)

    for scheduled in scheduler.get_jobs():
        if scheduled.id != SYNC_JOB_ID and scheduled.id not in active_ids:
            unregister_job(scheduled.id)


async def _run_sync_jobs() -> None:
    """Scheduler entry point for the periodic reconciliation."""
    from yaai.server import database  # noqa: PLC0415

    try:
        async with database.async_session() as db:
            await sync_jobs(db)
    except Exception:
        logger.exception("Scheduler reconciliation failed")


def start_job_sync() -> None:
    """Register the periodic reconciliation job that keeps this scheduler in sync with the database."""
    scheduler.add_job(
        _run_sync_jobs,
        IntervalTrigger(seconds=SYNC_INTERVAL_SECONDS),
        id=SYNC_JOB_ID,
        name="Scheduler reconciliation",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("Scheduler reconciliation every %d seconds", SYNC_INTERVAL_SECONDS)
