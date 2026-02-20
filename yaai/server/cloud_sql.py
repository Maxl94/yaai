"""Google Cloud SQL Connector integration.

Only imported when CLOUD_SQL_INSTANCE is configured.
Requires the 'gcp' extra: pip install "yaai-monitoring[gcp]"
"""

import logging

from google.cloud.sql.connector import Connector, IPTypes, create_async_connector
from sqlalchemy import create_engine

from yaai.server.config import settings

logger = logging.getLogger(__name__)

_IP_TYPE_MAP = {
    "public": IPTypes.PUBLIC,
    "private": IPTypes.PRIVATE,
    "psc": IPTypes.PSC,
}


class CloudSQLConnector:
    """Manages Cloud SQL Connector lifecycle for both async and sync connections."""

    def __init__(self) -> None:
        self._connector: Connector | None = None
        self._ip_type = _IP_TYPE_MAP.get(settings.cloud_sql_ip_type.lower(), IPTypes.PUBLIC)

    async def startup(self) -> None:
        self._connector = await create_async_connector(refresh_strategy="LAZY")
        logger.info(
            "Cloud SQL Connector initialized for instance=%s ip_type=%s iam_auth=%s",
            settings.cloud_sql_instance,
            settings.cloud_sql_ip_type,
            settings.cloud_sql_iam_auth,
        )

    async def shutdown(self) -> None:
        if self._connector:
            await self._connector.close_async()
            logger.info("Cloud SQL Connector closed.")

    async def async_creator(self):
        """Async connection creator for SQLAlchemy create_async_engine."""
        return await self._connector.connect_async(
            settings.cloud_sql_instance,
            "asyncpg",
            user=settings.cloud_sql_user,
            db=settings.cloud_sql_database,
            enable_iam_auth=settings.cloud_sql_iam_auth,
            ip_type=self._ip_type,
        )

    @staticmethod
    def create_sync_engine():
        """Create a sync SQLAlchemy engine with its own Connector.

        Intended for one-off tasks like migrations. Uses a standalone
        Connector so it never interferes with the async Connector's event loop.
        """
        ip_type = _IP_TYPE_MAP.get(settings.cloud_sql_ip_type.lower(), IPTypes.PUBLIC)
        connector = Connector()

        def _creator():
            return connector.connect(
                settings.cloud_sql_instance,
                "pg8000",
                user=settings.cloud_sql_user,
                db=settings.cloud_sql_database,
                enable_iam_auth=settings.cloud_sql_iam_auth,
                ip_type=ip_type,
            )

        return create_engine("postgresql+pg8000://", creator=_creator)
