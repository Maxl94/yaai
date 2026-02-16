"""Unit tests for the scheduler module."""

from unittest.mock import MagicMock, patch

import pytest

from yaai.server.scheduler import register_job, unregister_job


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
