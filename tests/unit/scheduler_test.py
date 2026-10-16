"""Unit tests for the scheduler module."""

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yaai.server.scheduler import (
    _execute_scheduled_job,
    _try_acquire_job_lock,
    job_lock_key,
    register_job,
    scheduler_enabled,
    unregister_job,
)


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
    async def test_postgres_returns_advisory_lock_result(self, acquired):
        job_id = uuid.uuid4()
        conn = MagicMock()
        conn.dialect.name = "postgresql"
        conn.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=acquired)))

        assert await _try_acquire_job_lock(conn, job_id) is acquired
        assert conn.execute.call_args.args[1] == {"key": job_lock_key(job_id)}


class TestExecuteScheduledJob:
    @pytest.fixture
    def patched(self):
        """Patch the database engine and DriftService used by _execute_scheduled_job."""
        lock_conn = MagicMock()
        lock_conn.begin.return_value = AsyncContextManager()
        engine = MagicMock()
        engine.connect.return_value = AsyncContextManager(lock_conn)
        session_factory = MagicMock(return_value=AsyncContextManager())
        run = MagicMock(status="completed")
        with (
            patch("yaai.server.database.engine", engine),
            patch("yaai.server.database.async_session", session_factory),
            patch("yaai.server.scheduler._try_acquire_job_lock", new_callable=AsyncMock) as acquire,
            patch("yaai.server.services.drift_service.DriftService") as drift_service,
        ):
            drift_service.return_value.execute_job = AsyncMock(return_value=run)
            yield acquire, drift_service

    async def test_runs_job_when_lock_acquired(self, patched):
        acquire, drift_service = patched
        acquire.return_value = True
        job_id = uuid.uuid4()

        await _execute_scheduled_job(str(job_id))

        drift_service.return_value.execute_job.assert_awaited_once_with(job_id)

    async def test_skips_job_when_lock_not_acquired(self, patched, caplog):
        acquire, drift_service = patched
        acquire.return_value = False

        with caplog.at_level(logging.INFO):
            await _execute_scheduled_job(str(uuid.uuid4()))

        drift_service.return_value.execute_job.assert_not_called()
        assert "already running on another instance" in caplog.text

    async def test_job_failure_is_logged_not_raised(self, patched, caplog):
        acquire, drift_service = patched
        acquire.return_value = True
        drift_service.return_value.execute_job.side_effect = RuntimeError("boom")

        await _execute_scheduled_job(str(uuid.uuid4()))

        assert "failed" in caplog.text


class TestSchedulerEnabled:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)
        assert scheduler_enabled() is True

    @pytest.mark.parametrize("value", ["false", "FALSE", "0", "no"])
    def test_can_be_disabled(self, monkeypatch, value):
        monkeypatch.setenv("SCHEDULER_ENABLED", value)
        assert scheduler_enabled() is False
