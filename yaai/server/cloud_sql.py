"""Google Cloud SQL Connector integration.

Only imported when CLOUD_SQL_INSTANCE is configured.
Requires the 'gcp' extra: pip install "yaai-monitoring[gcp]"
"""

import logging

from google.cloud.sql.connector import Connector, IPTypes

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
        self._connector = Connector(refresh_strategy="LAZY")
        logger.info(
            "Cloud SQL Connector initialized for instance=%s ip_type=%s iam_auth=%s",
            settings.cloud_sql_instance,
            settings.cloud_sql_ip_type,
            settings.cloud_sql_iam_auth,
        )

    async def shutdown(self) -> None:
        if self._connector:
            self._connector.close()
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

    def sync_creator(self):
        """Sync connection creator for SQLAlchemy create_engine (Alembic migrations)."""
        return self._connector.connect(
            settings.cloud_sql_instance,
            "pg8000",
            user=settings.cloud_sql_user,
            db=settings.cloud_sql_database,
            enable_iam_auth=settings.cloud_sql_iam_auth,
            ip_type=self._ip_type,
        )
