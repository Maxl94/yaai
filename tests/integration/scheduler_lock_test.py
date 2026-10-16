"""Integration tests: advisory lock for scheduled jobs and its connection usage on PostgreSQL."""

import asyncio
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from yaai.server.scheduler import _execute_scheduled_job, job_lock_key

LOCKS_QUERY = text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted")


class FakeDriftService:
    """DriftService stand-in whose execute_job behavior is injected per test."""

    handler = None

    def __init__(self, db):
        self.db = db

    async def execute_job(self, job_id: uuid.UUID):
        return await type(self).handler(self.db, job_id)


@contextmanager
def _patched(engine, handler):
    FakeDriftService.handler = handler
    with (
        patch("yaai.server.database.engine", engine),
        patch("yaai.server.services.drift_service.DriftService", FakeDriftService),
    ):
        yield


async def _held_advisory_locks(engine) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(LOCKS_QUERY)).scalar()


async def test_concurrent_scheduled_executions_run_only_once(pg_url):
    engine = create_async_engine(pg_url)
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[uuid.UUID] = []

    async def slow_execute_job(db, job_id: uuid.UUID):
        calls.append(job_id)
        started.set()
        await release.wait()
        return MagicMock(status="completed")

    job_id = uuid.uuid4()
    try:
        with _patched(engine, slow_execute_job):
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
            assert await _held_advisory_locks(engine) == 0
    finally:
        await engine.dispose()


async def test_job_runs_on_the_connection_holding_the_lock(pg_url):
    engine = create_async_engine(pg_url, pool_size=1, max_overflow=0, pool_timeout=5)
    job_id = uuid.uuid4()
    seen: dict[str, object] = {}

    async def inspect_job(db, _job_id: uuid.UUID):
        key = job_lock_key(job_id)
        pid = (await db.execute(text("SELECT pg_backend_pid()"))).scalar()
        holder = (
            await db.execute(
                text("SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted AND objid = :obj"),
                {"obj": key & 0xFFFFFFFF},
            )
        ).scalar()
        await db.commit()  # commits inside the job must not release the lock
        still_held = (await db.execute(LOCKS_QUERY)).scalar()
        seen.update(pid=pid, holder=holder, still_held=still_held)
        return MagicMock(status="completed")

    try:
        with _patched(engine, inspect_job):
            await asyncio.wait_for(_execute_scheduled_job(str(job_id)), timeout=10)
        assert seen["holder"] == seen["pid"]
        assert seen["still_held"] == 1
        assert await _held_advisory_locks(engine) == 0
    finally:
        await engine.dispose()


async def test_more_concurrent_jobs_than_pool_connections_all_complete(pg_url):
    engine = create_async_engine(pg_url, pool_size=2, max_overflow=0, pool_timeout=5)
    completed: list[uuid.UUID] = []

    async def quick_job(db, job_id: uuid.UUID):
        await db.execute(text("SELECT pg_sleep(0.2)"))
        await db.commit()
        completed.append(job_id)
        return MagicMock(status="completed")

    job_ids = [uuid.uuid4() for _ in range(6)]
    try:
        with _patched(engine, quick_job):
            await asyncio.wait_for(asyncio.gather(*(_execute_scheduled_job(str(j)) for j in job_ids)), timeout=30)
        assert sorted(completed) == sorted(job_ids)
        assert await _held_advisory_locks(engine) == 0
    finally:
        await engine.dispose()


async def test_lock_is_released_when_the_job_fails(pg_url):
    engine = create_async_engine(pg_url, pool_size=1, max_overflow=0, pool_timeout=5)
    job_id = uuid.uuid4()

    async def failing_job(db, _job_id: uuid.UUID):
        raise RuntimeError("boom")

    try:
        with _patched(engine, failing_job):
            await asyncio.wait_for(_execute_scheduled_job(str(job_id)), timeout=10)
        # The single pooled connection must be reusable and must no longer hold the lock.
        assert await _held_advisory_locks(engine) == 0
    finally:
        await engine.dispose()


@pytest.mark.parametrize("n_jobs", [1, 3])
async def test_same_job_concurrently_runs_once_with_small_pool(pg_url, n_jobs):
    engine = create_async_engine(pg_url, pool_size=2, max_overflow=0, pool_timeout=5)
    calls: list[uuid.UUID] = []

    async def slow_job(db, job_id: uuid.UUID):
        calls.append(job_id)
        await db.execute(text("SELECT pg_sleep(0.5)"))
        return MagicMock(status="completed")

    job_id = uuid.uuid4()
    try:
        with _patched(engine, slow_job):
            await asyncio.wait_for(asyncio.gather(*(_execute_scheduled_job(str(job_id)) for _ in range(n_jobs))), 30)
        assert calls == [job_id]
    finally:
        await engine.dispose()
