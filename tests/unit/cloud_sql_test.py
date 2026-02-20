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
    """Mock the Connector instance returned by Connector()."""
    instance = MagicMock()
    instance.connect_async = AsyncMock(return_value=MagicMock(name="async_conn"))
    instance.connect = MagicMock(return_value=MagicMock(name="sync_conn"))
    instance.close = MagicMock()
    _mock_connector_module.Connector.return_value = instance
    yield instance


class TestCloudSQLConnector:
    async def test_startup_creates_connector(self, mock_settings, mock_connector_instance):
        connector = CloudSQLConnector()
        await connector.startup()

        _mock_connector_module.Connector.assert_called_with(refresh_strategy="LAZY")
        assert connector._connector is mock_connector_instance

    async def test_shutdown_closes_connector(self, mock_settings, mock_connector_instance):
        connector = CloudSQLConnector()
        await connector.startup()
        await connector.shutdown()

        mock_connector_instance.close.assert_called_once()

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

    async def test_sync_creator_calls_connect(self, mock_settings, mock_connector_instance):
        connector = CloudSQLConnector()
        await connector.startup()
        result = connector.sync_creator()

        mock_connector_instance.connect.assert_called_once_with(
            "my-project:us-central1:my-instance",
            "pg8000",
            user="sa@my-project.iam.gserviceaccount.com",
            db="testdb",
            enable_iam_auth=True,
            ip_type=_MockIPTypes.PUBLIC,
        )
        assert result == mock_connector_instance.connect.return_value

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
        ):
            mock_cfg = MagicMock()
            mock_cfg_cls.return_value = mock_cfg

            main_mod._apply_migrations(sync_creator=None)

            mock_cfg.set_main_option.assert_called_once()
            mock_command.upgrade.assert_called_once_with(mock_cfg, "head")

    def test_apply_migrations_with_sync_creator(self):
        import yaai.server.main as main_mod

        mock_creator = MagicMock(return_value=MagicMock())
        mock_connection = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_connection)
        mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(main_mod, "AlembicConfig") as mock_cfg_cls,
            patch.object(main_mod, "command") as mock_command,
            patch("sqlalchemy.create_engine", return_value=mock_engine) as mock_create,
        ):
            mock_cfg = MagicMock()
            mock_cfg.attributes = {}
            mock_cfg_cls.return_value = mock_cfg

            main_mod._apply_migrations(sync_creator=mock_creator)

            mock_create.assert_called_once_with("postgresql+pg8000://", creator=mock_creator)
            assert mock_cfg.attributes["connection"] is mock_connection
            mock_command.upgrade.assert_called_once_with(mock_cfg, "head")
            mock_cfg.set_main_option.assert_not_called()
