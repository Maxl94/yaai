"""Unit tests for Cloud SQL Connector integration (mocked).

The google.cloud.sql.connector package is not installed in the test environment,
so we install a mock module in sys.modules before importing cloud_sql.
"""

import sys
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- Mock google.cloud.sql.connector at the sys.modules level ---
class _MockIPTypes(Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    PSC = "PSC"


_mock_connector_module = MagicMock()
_mock_connector_module.IPTypes = _MockIPTypes
_mock_connector_module.Connector = MagicMock()

# Install the mock before any import of cloud_sql can happen
sys.modules.setdefault("google.cloud.sql.connector", _mock_connector_module)

from yaai.server.cloud_sql import CloudSQLConnector  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_connector_mock():
    """Reset mock call counts between tests."""
    _mock_connector_module.Connector.reset_mock()


@pytest.fixture
def mock_settings():
    """Provide mock settings for Cloud SQL configuration."""
    with patch("yaai.server.cloud_sql.settings") as mock:
        mock.cloud_sql_instance = "my-project:us-central1:my-instance"
        mock.cloud_sql_ip_type = "public"
        mock.cloud_sql_iam_auth = True
        mock.cloud_sql_database = "testdb"
        mock.cloud_sql_user = "sa@my-project.iam.gserviceaccount.com"
        yield mock


@pytest.fixture
def mock_connector_instance():
    """Mock the Connector instance returned by create_async_connector()."""
    instance = MagicMock()
    instance.connect_async = AsyncMock(return_value=MagicMock(name="async_conn"))
    instance.connect = MagicMock(return_value=MagicMock(name="sync_conn"))
    instance.close_async = AsyncMock()
    _mock_connector_module.Connector.return_value = instance
    # create_async_connector is imported by name in cloud_sql.py, so patch it there directly
    with patch("yaai.server.cloud_sql.create_async_connector", AsyncMock(return_value=instance)):
        yield instance


class TestCloudSQLConnector:
    async def test_startup_creates_connector(self, mock_settings, mock_connector_instance):
        connector = CloudSQLConnector()
        await connector.startup()

        # create_async_connector was awaited and its return value stored
        assert connector._connector is mock_connector_instance

    async def test_shutdown_closes_connector(self, mock_settings, mock_connector_instance):
        connector = CloudSQLConnector()
        await connector.startup()
        await connector.shutdown()

        mock_connector_instance.close_async.assert_called_once()

    async def test_shutdown_without_startup_is_safe(self, mock_settings, mock_connector_instance):
        connector = CloudSQLConnector()
        await connector.shutdown()

    async def test_async_creator_calls_connect_async(self, mock_settings, mock_connector_instance):
        connector = CloudSQLConnector()
        await connector.startup()
        result = await connector.async_creator()

        mock_connector_instance.connect_async.assert_called_once_with(
            "my-project:us-central1:my-instance",
            "asyncpg",
            user="sa@my-project.iam.gserviceaccount.com",
            db="testdb",
            enable_iam_auth=True,
            ip_type=_MockIPTypes.PUBLIC,
        )
        assert result == mock_connector_instance.connect_async.return_value

    def test_create_sync_engine_connects_via_pg8000(self, mock_settings, mock_connector_instance):
        """create_sync_engine() builds a standalone sync engine using pg8000."""
        mock_sync_conn = MagicMock(name="sync_conn")
        mock_sync_connector = MagicMock()
        mock_sync_connector.connect.return_value = mock_sync_conn
        _mock_connector_module.Connector.return_value = mock_sync_connector

        with patch("yaai.server.cloud_sql.create_engine") as mock_create_engine:
            mock_engine = MagicMock()
            mock_create_engine.return_value = mock_engine

            result = CloudSQLConnector.create_sync_engine()

            mock_create_engine.assert_called_once()
            call_args = mock_create_engine.call_args
            assert call_args.args[0] == "postgresql+pg8000://"
            assert result is mock_engine

    async def test_ip_type_private(self, mock_settings, mock_connector_instance):
        mock_settings.cloud_sql_ip_type = "private"
        connector = CloudSQLConnector()
        await connector.startup()
        await connector.async_creator()

        call_kwargs = mock_connector_instance.connect_async.call_args.kwargs
        assert call_kwargs["ip_type"] == _MockIPTypes.PRIVATE

    async def test_ip_type_psc(self, mock_settings, mock_connector_instance):
        mock_settings.cloud_sql_ip_type = "psc"
        connector = CloudSQLConnector()
        await connector.startup()
        await connector.async_creator()

        call_kwargs = mock_connector_instance.connect_async.call_args.kwargs
        assert call_kwargs["ip_type"] == _MockIPTypes.PSC

    async def test_iam_auth_disabled(self, mock_settings, mock_connector_instance):
        mock_settings.cloud_sql_iam_auth = False
        connector = CloudSQLConnector()
        await connector.startup()
        await connector.async_creator()

        call_kwargs = mock_connector_instance.connect_async.call_args.kwargs
        assert call_kwargs["enable_iam_auth"] is False

    async def test_ip_type_defaults_to_public_for_unknown(self, mock_settings, mock_connector_instance):
        mock_settings.cloud_sql_ip_type = "unknown_value"
        connector = CloudSQLConnector()
        await connector.startup()
        await connector.async_creator()

        call_kwargs = mock_connector_instance.connect_async.call_args.kwargs
        assert call_kwargs["ip_type"] == _MockIPTypes.PUBLIC


class TestInitEngine:
    def test_init_engine_without_creator_uses_database_url(self):
        with patch("yaai.server.database.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            from yaai.server import database

            database.init_engine()

            mock_create.assert_called_with(database.settings.database_url, echo=False)
            assert database.engine is not None
            assert database.async_session is not None

    def test_init_engine_with_creator_uses_async_creator(self):
        mock_creator = AsyncMock()
        with patch("yaai.server.database.create_async_engine") as mock_create:
            mock_create.return_value = MagicMock()
            from yaai.server import database

            database.init_engine(async_creator=mock_creator)

            mock_create.assert_called_with(
                "postgresql+asyncpg://",
                async_creator=mock_creator,
                echo=False,
            )

    def test_init_engine_replaces_existing_engine(self):
        with patch("yaai.server.database.create_async_engine") as mock_create:
            mock_engine_1 = MagicMock(name="engine1")
            mock_engine_2 = MagicMock(name="engine2")
            mock_create.side_effect = [mock_engine_1, mock_engine_2]

            from yaai.server import database

            database.init_engine()
            assert database.engine is mock_engine_1

            database.init_engine()
            assert database.engine is mock_engine_2


class TestApplyMigrations:
    """Test _apply_migrations via the already-imported main module."""

    def test_apply_migrations_without_cloud_sql(self):
        import yaai.server.main as main_mod

        with (
            patch.object(main_mod, "AlembicConfig") as mock_cfg_cls,
            patch.object(main_mod, "command") as mock_command,
            patch.object(main_mod, "settings") as mock_s,
        ):
            mock_s.cloud_sql_instance = None
            mock_s.database_url_sync = "sqlite:///test.db"
            mock_cfg = MagicMock()
            mock_cfg_cls.return_value = mock_cfg

            main_mod._apply_migrations()

            mock_cfg.set_main_option.assert_called_once()
            mock_command.upgrade.assert_called_once_with(mock_cfg, "head")

    def test_apply_migrations_with_cloud_sql(self):
        import yaai.server.main as main_mod
        from yaai.server.cloud_sql import CloudSQLConnector

        mock_connection = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_connection)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(main_mod, "AlembicConfig") as mock_cfg_cls,
            patch.object(main_mod, "command") as mock_command,
            patch.object(main_mod, "settings") as mock_s,
            patch.object(CloudSQLConnector, "create_sync_engine", return_value=mock_engine),
        ):
            mock_s.cloud_sql_instance = "my-project:us-central1:my-instance"
            mock_cfg = MagicMock()
            mock_cfg.attributes = {}
            mock_cfg_cls.return_value = mock_cfg

            main_mod._apply_migrations()

            assert mock_cfg.attributes["connection"] is mock_connection
            mock_command.upgrade.assert_called_once_with(mock_cfg, "head")
            mock_cfg.set_main_option.assert_not_called()
