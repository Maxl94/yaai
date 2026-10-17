"""Unit tests for the headless worker."""

import asyncio
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import yaai.server.startup as startup_mod
import yaai.server.worker as worker_mod
from yaai.server.migrate import SchemaNotUpToDateError


async def _until(condition) -> None:
    while not condition():
        await asyncio.sleep(0)


@pytest.fixture
def parts():
    """Patch the startup collaborators and record the call order."""
    calls: list[str] = []
    scheduler = MagicMock(running=False)
    scheduler.start.side_effect = lambda: (calls.append("scheduler.start"), setattr(scheduler, "running", True))
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    session_cm.__aexit__ = AsyncMock(return_value=False)
    with (
        patch.object(startup_mod, "check_schema_up_to_date", side_effect=lambda: calls.append("schema")),
        patch.object(startup_mod.database, "async_session", MagicMock(return_value=session_cm)),
        patch.object(
            startup_mod, "load_active_jobs", new_callable=AsyncMock, side_effect=lambda db: calls.append("load")
        ),
        patch.object(startup_mod, "start_job_sync", side_effect=lambda: calls.append("sync")),
        patch.object(startup_mod, "scheduler", scheduler),
    ):
        yield calls, scheduler


class TestRun:
    async def test_starts_scheduler_in_order_and_shuts_down_when_stopped(self, parts):
        calls, scheduler = parts
        stop = asyncio.Event()

        task = asyncio.create_task(worker_mod.run(stop))
        await asyncio.wait_for(_until(lambda: scheduler.running), timeout=5)

        assert calls == ["schema", "load", "sync", "scheduler.start"]
        assert not task.done()
        scheduler.shutdown.assert_not_called()

        stop.set()
        await task
        scheduler.shutdown.assert_called_once_with(wait=False)

    async def test_ignores_scheduler_enabled_false(self, parts, monkeypatch):
        calls, scheduler = parts
        monkeypatch.setenv("SCHEDULER_ENABLED", "false")
        stop = asyncio.Event()
        stop.set()

        await worker_mod.run(stop)

        scheduler.start.assert_called_once()

    async def test_schema_behind_raises_before_scheduler_starts(self, parts):
        calls, scheduler = parts
        with patch.object(startup_mod, "check_schema_up_to_date", side_effect=SchemaNotUpToDateError("behind")):
            with pytest.raises(SchemaNotUpToDateError):
                await worker_mod.run(asyncio.Event())

        scheduler.start.assert_not_called()

    async def test_scheduler_failure_still_shuts_down_cloud_sql(self, parts):
        cloud_sql = MagicMock(shutdown=AsyncMock())
        with (
            patch.object(startup_mod, "init_database", AsyncMock(return_value=cloud_sql)),
            patch.object(startup_mod, "start_scheduler", AsyncMock(side_effect=RuntimeError("db down"))),
            pytest.raises(RuntimeError, match="db down"),
        ):
            await worker_mod.run(asyncio.Event())

        cloud_sql.shutdown.assert_awaited_once()


class TestMain:
    @pytest.mark.parametrize("error", [SchemaNotUpToDateError("behind"), RuntimeError("boom")])
    def test_startup_failure_exits_non_zero(self, error):
        with patch.object(worker_mod, "_run_until_signalled", side_effect=error), pytest.raises(SystemExit) as exc:
            worker_mod.main()

        assert exc.value.code == 1


def test_importing_worker_registers_all_orm_models():
    code = "import yaai.server.worker; from sqlalchemy.orm import configure_mappers; configure_mappers()"

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)  # noqa: S603

    assert result.returncode == 0, result.stderr
