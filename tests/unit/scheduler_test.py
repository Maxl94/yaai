"""Unit tests for the scheduler module."""

import logging
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from yaai.server.models.job import ComparisonType, JobConfig
from yaai.server.models.model import Model, ModelVersion
from yaai.server.scheduler import (
    SYNC_JOB_ID,
    _execute_scheduled_job,
    _release_job_lock,
    _run_sync_jobs,
    _try_acquire_job_lock,
    job_lock_key,
    register_job,
    scheduler_enabled,
    scheduler_sync_interval_seconds,
    start_job_sync,
    sync_jobs,
    unregister_job,
)
from yaai.server.services.project_service import get_or_create_default_project


class AsyncContextManager:
    """Minimal async context manager yielding a given value."""

    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def mock_scheduler():
    with patch("yaai.server.scheduler.scheduler") as mock:
        mock.get_job.return_value = None
        yield mock


def test_register_job_adds_to_scheduler(mock_scheduler):
    """Registering an active job should add it to the scheduler."""
    job_config = MagicMock()
    job_config.id = "test-job-id"
    job_config.name = "Test Job"
    job_config.schedule = "0 * * * *"
    job_config.is_active = True

    register_job(job_config)

    mock_scheduler.add_job.assert_called_once()
    call_args = mock_scheduler.add_job.call_args
    assert call_args.kwargs["id"] == "test-job-id"
    assert call_args.kwargs["name"] == "Test Job"


def test_register_job_removes_existing_before_add(mock_scheduler):
    """Registering a job should remove existing job with same ID first."""
    mock_scheduler.get_job.return_value = MagicMock()

    job_config = MagicMock()
    job_config.id = "test-job-id"
    job_config.name = "Test Job"
    job_config.schedule = "0 * * * *"
    job_config.is_active = True

    register_job(job_config)

    mock_scheduler.remove_job.assert_called_once_with("test-job-id")
    mock_scheduler.add_job.assert_called_once()


def test_register_inactive_job_does_not_add(mock_scheduler):
    """Registering an inactive job should not add it to the scheduler."""
    job_config = MagicMock()
    job_config.id = "test-job-id"
    job_config.name = "Test Job"
    job_config.schedule = "0 * * * *"
    job_config.is_active = False

    register_job(job_config)

    mock_scheduler.add_job.assert_not_called()


def test_register_inactive_job_removes_existing(mock_scheduler):
    """Registering an inactive job should remove it if it exists."""
    mock_scheduler.get_job.return_value = MagicMock()

    job_config = MagicMock()
    job_config.id = "test-job-id"
    job_config.name = "Test Job"
    job_config.schedule = "0 * * * *"
    job_config.is_active = False

    register_job(job_config)

    mock_scheduler.remove_job.assert_called_once_with("test-job-id")
    mock_scheduler.add_job.assert_not_called()


def test_unregister_job_removes_from_scheduler(mock_scheduler):
    """Unregistering a job should remove it from the scheduler."""
    mock_scheduler.get_job.return_value = MagicMock()

    unregister_job("test-job-id")

    mock_scheduler.remove_job.assert_called_once_with("test-job-id")


def test_unregister_nonexistent_job_no_error(mock_scheduler):
    """Unregistering a non-existent job should not raise an error."""
    mock_scheduler.get_job.return_value = None

    # Should not raise
    unregister_job("nonexistent-job-id")

    mock_scheduler.remove_job.assert_not_called()


class TestJobLockKey:
    def test_is_deterministic_signed_64_bit(self):
        job_id = uuid.uuid4()
        key = job_lock_key(job_id)
        assert key == job_lock_key(job_id)
        assert -(2**63) <= key < 2**63

    def test_differs_between_jobs(self):
        assert job_lock_key(uuid.uuid4()) != job_lock_key(uuid.uuid4())

    def test_high_bit_maps_to_negative(self):
        assert job_lock_key(uuid.UUID(int=0xFFFFFFFFFFFFFFFF << 64)) == -1


class TestTryAcquireJobLock:
    async def test_non_postgres_dialect_always_acquires(self):
        conn = MagicMock()
        conn.dialect.name = "sqlite"
        conn.execute = AsyncMock()

        assert await _try_acquire_job_lock(conn, uuid.uuid4()) is True
        conn.execute.assert_not_called()

    @pytest.mark.parametrize("acquired", [True, False])
    async def test_postgres_returns_session_lock_result_and_commits(self, acquired):
        job_id = uuid.uuid4()
        conn = MagicMock()
        conn.dialect.name = "postgresql"
        conn.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=acquired)))
        conn.commit = AsyncMock()

        assert await _try_acquire_job_lock(conn, job_id) is acquired
        assert "pg_try_advisory_lock" in str(conn.execute.call_args.args[0])
        assert conn.execute.call_args.args[1] == {"key": job_lock_key(job_id)}
        conn.commit.assert_awaited_once()


class TestReleaseJobLock:
    @pytest.fixture
    def conn(self):
        conn = MagicMock()
        conn.dialect.name = "postgresql"
        conn.execute = AsyncMock()
        conn.commit = AsyncMock()
        conn.rollback = AsyncMock()
        conn.invalidate = AsyncMock()
        return conn

    async def test_unlocks_on_the_same_connection(self, conn):
        job_id = uuid.uuid4()

        await _release_job_lock(conn, job_id)

        assert "pg_advisory_unlock" in str(conn.execute.call_args.args[0])
        assert conn.execute.call_args.args[1] == {"key": job_lock_key(job_id)}
        conn.invalidate.assert_not_called()

    async def test_invalidates_connection_when_unlock_fails(self, conn, caplog):
        conn.execute.side_effect = RuntimeError("connection lost")

        await _release_job_lock(conn, uuid.uuid4())

        conn.invalidate.assert_awaited_once()
        assert "Could not release advisory lock" in caplog.text

    async def test_non_postgres_is_noop(self, conn):
        conn.dialect.name = "sqlite"

        await _release_job_lock(conn, uuid.uuid4())

        conn.execute.assert_not_called()


class TestExecuteScheduledJob:
    @pytest.fixture
    def patched(self):
        """Patch the engine, session class and DriftService used by _execute_scheduled_job."""
        lock_conn = MagicMock()
        engine = MagicMock()
        engine.connect.return_value = AsyncContextManager(lock_conn)
        run = MagicMock(status="completed")
        with (
            patch("yaai.server.database.engine", engine),
            patch("yaai.server.scheduler.AsyncSession", return_value=AsyncContextManager()) as session_cls,
            patch("yaai.server.scheduler._try_acquire_job_lock", new_callable=AsyncMock) as acquire,
            patch("yaai.server.scheduler._release_job_lock", new_callable=AsyncMock) as release,
            patch("yaai.server.services.drift_service.DriftService") as drift_service,
        ):
            drift_service.return_value.execute_job = AsyncMock(return_value=run)
            yield SimpleNamespace(
                acquire=acquire, release=release, drift_service=drift_service, session_cls=session_cls, conn=lock_conn
            )

    async def test_runs_job_on_the_lock_connection_and_releases_lock(self, patched):
        patched.acquire.return_value = True
        job_id = uuid.uuid4()

        await _execute_scheduled_job(str(job_id))

        patched.drift_service.return_value.execute_job.assert_awaited_once_with(job_id)
        assert patched.session_cls.call_args.kwargs["bind"] is patched.conn
        patched.release.assert_awaited_once_with(patched.conn, job_id)

    async def test_skips_job_when_lock_not_acquired(self, patched, caplog):
        patched.acquire.return_value = False

        with caplog.at_level(logging.INFO):
            await _execute_scheduled_job(str(uuid.uuid4()))

        patched.drift_service.return_value.execute_job.assert_not_called()
        patched.release.assert_not_called()
        assert "already running on another instance" in caplog.text

    async def test_job_failure_is_logged_not_raised_and_lock_released(self, patched, caplog):
        patched.acquire.return_value = True
        patched.drift_service.return_value.execute_job.side_effect = RuntimeError("boom")

        await _execute_scheduled_job(str(uuid.uuid4()))

        assert "failed" in caplog.text
        patched.release.assert_awaited_once()


class TestSchedulerSync:
    @pytest.fixture
    def sync_scheduler(self):
        """Use a fresh, not-started scheduler (jobs stay pending) instead of the module singleton."""
        fresh = AsyncIOScheduler()
        with patch("yaai.server.scheduler.scheduler", fresh):
            yield fresh

    @staticmethod
    async def _add_job(db, name="Job", schedule="0 2 * * *", is_active=True) -> JobConfig:
        project = await get_or_create_default_project(db)
        model = Model(name=f"m-{uuid.uuid4()}", project_id=project.id)
        db.add(model)
        await db.flush()
        version = ModelVersion(model_id=model.id, version="1")
        db.add(version)
        await db.flush()
        job = JobConfig(
            model_version_id=version.id,
            name=name,
            schedule=schedule,
            comparison_type=ComparisonType.VS_REFERENCE,
            is_active=is_active,
        )
        db.add(job)
        await db.commit()
        return job

    async def test_adds_missing_active_jobs(self, db_session, sync_scheduler):
        job = await self._add_job(db_session)

        await sync_jobs(db_session)

        assert sync_scheduler.get_job(str(job.id)) is not None

    async def test_ignores_inactive_jobs(self, db_session, sync_scheduler):
        job = await self._add_job(db_session, is_active=False)

        await sync_jobs(db_session)

        assert sync_scheduler.get_job(str(job.id)) is None

    async def test_updates_job_when_schedule_changed(self, db_session, sync_scheduler):
        job = await self._add_job(db_session, schedule="0 2 * * *")
        await sync_jobs(db_session)
        before = str(sync_scheduler.get_job(str(job.id)).trigger)

        job.schedule = "30 4 * * *"
        await db_session.commit()
        await sync_jobs(db_session)

        assert str(sync_scheduler.get_job(str(job.id)).trigger) != before
        assert len(sync_scheduler.get_jobs()) == 1

    async def test_keeps_unchanged_job_untouched(self, db_session, sync_scheduler):
        job = await self._add_job(db_session)
        await sync_jobs(db_session)
        first = sync_scheduler.get_job(str(job.id))

        await sync_jobs(db_session)

        assert sync_scheduler.get_job(str(job.id)) is first

    async def test_removes_deactivated_and_deleted_jobs(self, db_session, sync_scheduler):
        deactivated = await self._add_job(db_session, name="a")
        deleted = await self._add_job(db_session, name="b")
        kept = await self._add_job(db_session, name="c")
        await sync_jobs(db_session)
        assert len(sync_scheduler.get_jobs()) == 3

        deactivated.is_active = False
        await db_session.delete(deleted)
        await db_session.commit()
        await sync_jobs(db_session)

        assert [j.id for j in sync_scheduler.get_jobs()] == [str(kept.id)]

    async def test_never_removes_the_sync_job(self, db_session, sync_scheduler):
        start_job_sync(60)

        await sync_jobs(db_session)

        assert sync_scheduler.get_job(SYNC_JOB_ID) is not None

    async def test_invalid_schedule_does_not_block_other_jobs(self, db_session, sync_scheduler, caplog):
        bad = await self._add_job(db_session, name="bad", schedule="not a cron")
        good = await self._add_job(db_session, name="good")

        await sync_jobs(db_session)

        assert sync_scheduler.get_job(str(bad.id)) is None
        assert sync_scheduler.get_job(str(good.id)) is not None
        assert "invalid schedule" in caplog.text

    async def test_run_sync_jobs_logs_errors_instead_of_raising(self, caplog):
        with patch("yaai.server.database.async_session", side_effect=RuntimeError("db down")):
            await _run_sync_jobs()

        assert "reconciliation failed" in caplog.text


class TestSchedulerSyncInterval:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("SCHEDULER_SYNC_INTERVAL_SECONDS", raising=False)
        assert scheduler_sync_interval_seconds() == 60

    def test_custom_value(self, monkeypatch):
        monkeypatch.setenv("SCHEDULER_SYNC_INTERVAL_SECONDS", "15")
        assert scheduler_sync_interval_seconds() == 15

    @pytest.mark.parametrize("value", ["abc", "0", "-5", ""])
    def test_invalid_value_uses_default(self, monkeypatch, value):
        monkeypatch.setenv("SCHEDULER_SYNC_INTERVAL_SECONDS", value)
        assert scheduler_sync_interval_seconds() == 60


class TestSchedulerEnabled:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
        assert scheduler_enabled() is True

    @pytest.mark.parametrize("value", ["false", "FALSE", "0", "no"])
    def test_can_be_disabled(self, monkeypatch, value):
        monkeypatch.setenv("SCHEDULER_ENABLED", value)
        assert scheduler_enabled() is False
