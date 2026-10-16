"""Unit tests for the startup schema check (mocked revision lookups)."""

import sys
from unittest.mock import MagicMock, patch

import pytest

import yaai.server.migrate as migrate_mod
from yaai.server.migrate import SchemaNotUpToDateError, check_schema_up_to_date


def _patched_check(current: str | None, head: str | None, cloud_sql: str | None = None):
    mock_engine = MagicMock()
    mock_settings = MagicMock(cloud_sql_instance=cloud_sql, database_url_sync="sqlite://")
    return mock_engine, (
        patch.object(migrate_mod, "settings", mock_settings),
        patch.object(migrate_mod, "create_engine", return_value=mock_engine),
        patch.object(migrate_mod, "get_migration_status", return_value=(current, head)),
    )


class TestCheckSchemaUpToDate:
    def test_up_to_date_does_not_raise(self):
        engine, (p1, p2, p3) = _patched_check("abc123", "abc123")
        with p1, p2, p3:
            check_schema_up_to_date()
        engine.dispose.assert_called_once()

    def test_behind_raises_with_instruction(self):
        engine, (p1, p2, p3) = _patched_check("old111", "new222")
        with p1, p2, p3, pytest.raises(SchemaNotUpToDateError) as exc_info:
            check_schema_up_to_date()

        message = str(exc_info.value)
        assert "old111" in message
        assert "new222" in message
        assert "python -m yaai.server.migrate" in message
        engine.dispose.assert_called_once()

    def test_empty_database_raises(self):
        _, (p1, p2, p3) = _patched_check(None, "new222")
        with p1, p2, p3, pytest.raises(SchemaNotUpToDateError, match="current revision: none"):
            check_schema_up_to_date()

    def test_uses_cloud_sql_engine_when_configured(self):
        mock_engine = MagicMock()
        mock_settings = MagicMock(cloud_sql_instance="proj:region:inst")
        mock_cloud_sql = MagicMock()
        mock_cloud_sql.CloudSQLConnector.create_sync_engine.return_value = mock_engine
        with (
            patch.object(migrate_mod, "settings", mock_settings),
            patch.dict(sys.modules, {"yaai.server.cloud_sql": mock_cloud_sql}),
            patch.object(migrate_mod, "create_engine") as mock_create_engine,
            patch.object(migrate_mod, "get_migration_status", return_value=("a", "a")),
        ):
            check_schema_up_to_date()

        mock_create_engine.assert_not_called()
        mock_engine.dispose.assert_called_once()


class TestGetMigrationStatus:
    def test_returns_current_and_head(self):
        connection = MagicMock()
        with (
            patch.object(migrate_mod, "MigrationContext") as mock_ctx,
            patch.object(migrate_mod, "ScriptDirectory") as mock_script,
        ):
            mock_ctx.configure.return_value.get_current_revision.return_value = "cur"
            mock_script.from_config.return_value.get_current_head.return_value = "head"

            assert migrate_mod.get_migration_status(connection) == ("cur", "head")

        mock_ctx.configure.assert_called_once_with(connection)

    def test_alembic_scripts_have_a_head(self):
        from alembic.script import ScriptDirectory

        assert ScriptDirectory.from_config(migrate_mod._alembic_config()).get_current_head()


class TestLifespanSchemaCheck:
    async def test_startup_aborts_when_schema_is_behind(self, caplog):
        import yaai.server.main as main_mod

        error = SchemaNotUpToDateError("Run `python -m yaai.server.migrate` before starting the server.")
        with (
            patch.object(main_mod, "check_schema_up_to_date", side_effect=error),
            caplog.at_level("ERROR"),
            pytest.raises(SchemaNotUpToDateError),
        ):
            async with main_mod.lifespan(main_mod.app):
                pass

        assert "python -m yaai.server.migrate" in caplog.text
