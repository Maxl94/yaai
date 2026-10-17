"""Unit tests for the admin bootstrap and the scheduler branches of the app lifespan."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import yaai.server.main as main_mod
from yaai.server.auth.config import AuthConfig
from yaai.server.auth.dependencies import set_auth_config
from yaai.server.auth.passwords import verify_password
from yaai.server.models.auth import User, UserRole

PASSWORD = "a-long-enough-password"  # noqa: S105


@pytest.fixture
def bootstrap_db(db_session):
    """Make _bootstrap_admin use the in-memory SQLite test database."""
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    with patch.object(main_mod.database, "async_session", factory):
        yield db_session


async def _users(db: AsyncSession) -> list[User]:
    return list((await db.execute(select(User))).scalars().all())


class TestBootstrapAdmin:
    async def test_creates_owner_with_configured_password_and_logs_nothing_secret(
        self, bootstrap_db, monkeypatch, caplog, capsys
    ):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", PASSWORD)

        with caplog.at_level(logging.DEBUG):
            await main_mod._bootstrap_admin()

        (user,) = await _users(bootstrap_db)
        assert user.username == "admin"
        assert user.role == UserRole.OWNER
        assert user.hashed_password != PASSWORD
        assert verify_password(PASSWORD, user.hashed_password)
        assert PASSWORD not in caplog.text
        assert PASSWORD not in capsys.readouterr().err

    async def test_too_short_password_aborts_startup_without_creating_user(self, bootstrap_db, monkeypatch):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "short")

        with pytest.raises(RuntimeError, match="too short"):
            await main_mod._bootstrap_admin()

        assert await _users(bootstrap_db) == []

    async def test_generated_password_is_written_to_file_before_user_is_created(
        self, bootstrap_db, monkeypatch, tmp_path, caplog
    ):
        monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
        target = tmp_path / "pw.txt"
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", str(target))

        with caplog.at_level(logging.DEBUG):
            await main_mod._bootstrap_admin()

        (user,) = await _users(bootstrap_db)
        generated = target.read_text().splitlines()[1].removeprefix("password: ")
        assert verify_password(generated, user.hashed_password)
        assert generated not in caplog.text

    async def test_no_user_is_created_when_password_cannot_be_delivered(self, bootstrap_db, monkeypatch, tmp_path):
        monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", str(tmp_path / "missing-dir" / "pw.txt"))

        with (
            patch("builtins.print", side_effect=OSError("stderr closed")),
            pytest.raises(RuntimeError, match="BOOTSTRAP_ADMIN_PASSWORD"),
        ):
            await main_mod._bootstrap_admin()

        assert await _users(bootstrap_db) == []

    async def test_password_file_is_removed_when_user_cannot_be_committed(self, bootstrap_db, monkeypatch, tmp_path):
        monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
        target = tmp_path / "pw.txt"
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", str(target))

        with (
            patch.object(AsyncSession, "commit", side_effect=RuntimeError("db down")),
            pytest.raises(RuntimeError, match="db down"),
        ):
            await main_mod._bootstrap_admin()

        assert not target.exists()

    async def test_does_nothing_when_users_exist(self, bootstrap_db, monkeypatch, tmp_path):
        bootstrap_db.add(User(username="existing", hashed_password="x", role=UserRole.OWNER))  # noqa: S106
        await bootstrap_db.commit()
        monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", str(tmp_path / "pw.txt"))

        await main_mod._bootstrap_admin()

        assert [u.username for u in await _users(bootstrap_db)] == ["existing"]
        assert not (tmp_path / "pw.txt").exists()


class TestLifespanScheduler:
    @pytest.fixture
    def lifespan_env(self):
        set_auth_config(AuthConfig(enabled=False))
        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
        session_cm.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(main_mod, "check_schema_up_to_date"),
            patch.object(main_mod.database, "async_session", MagicMock(return_value=session_cm)),
            patch.object(main_mod, "load_active_jobs", new_callable=AsyncMock) as load_jobs,
            patch.object(main_mod, "start_job_sync") as start_sync,
            patch.object(main_mod, "scheduler") as scheduler,
        ):
            scheduler.running = False
            yield load_jobs, start_sync, scheduler

    async def test_scheduler_disabled_does_not_start_or_shut_down(self, lifespan_env, monkeypatch):
        load_jobs, start_sync, scheduler = lifespan_env
        monkeypatch.setenv("SCHEDULER_ENABLED", "false")

        async with main_mod.lifespan(main_mod.app):
            pass

        load_jobs.assert_not_called()
        start_sync.assert_not_called()
        scheduler.start.assert_not_called()
        scheduler.shutdown.assert_not_called()

    async def test_scheduler_enabled_loads_jobs_syncs_and_shuts_down(self, lifespan_env, monkeypatch):
        load_jobs, start_sync, scheduler = lifespan_env
        monkeypatch.delenv("SCHEDULER_ENABLED", raising=False)

        async with main_mod.lifespan(main_mod.app):
            scheduler.running = True

        load_jobs.assert_awaited_once()
        start_sync.assert_called_once_with()
        scheduler.start.assert_called_once()
        scheduler.shutdown.assert_called_once_with(wait=False)
