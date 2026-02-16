from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.models.job import JobConfig

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _execute_scheduled_job(job_config_id: str) -> None:
    """Called by APScheduler when a cron trigger fires."""
    import uuid

    from yaai.server.database import async_session
    from yaai.server.services.drift_service import DriftService

    async with async_session() as db:
        svc = DriftService(db)
        try:
            run = await svc.execute_job(uuid.UUID(job_config_id))
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
