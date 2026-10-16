"""Integration test: the advisory lock prevents concurrent execution of the same scheduled job."""

import asyncio
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from yaai.server.scheduler import _execute_scheduled_job


async def test_concurrent_scheduled_executions_run_only_once(pg_url):
    engine = create_async_engine(pg_url)
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[uuid.UUID] = []

    async def slow_execute_job(job_id: uuid.UUID):
        calls.append(job_id)
        started.set()
        await release.wait()
        return MagicMock(status="completed")

    job_id = uuid.uuid4()
    try:
        with (
            patch("yaai.server.database.engine", engine),
            patch("yaai.server.database.async_session", async_sessionmaker(engine, expire_on_commit=False)),
            patch("yaai.server.services.drift_service.DriftService") as drift_service,
        ):
            drift_service.return_value.execute_job = slow_execute_job

            first = asyncio.create_task(_execute_scheduled_job(str(job_id)))
            await asyncio.wait_for(started.wait(), timeout=10)

            # Second "instance" fires while the first still holds the lock: it must skip.
            await asyncio.wait_for(_execute_scheduled_job(str(job_id)), timeout=10)
            assert calls == [job_id]

            # A different job is not blocked.
            other_job = uuid.uuid4()
            other = asyncio.create_task(_execute_scheduled_job(str(other_job)))
            await asyncio.sleep(0.5)
            assert calls == [job_id, other_job]

            release.set()
            await asyncio.gather(first, other)

            # Lock is released once the first execution finished.
            await _execute_scheduled_job(str(job_id))
            assert calls == [job_id, other_job, job_id]
    finally:
        await engine.dispose()
