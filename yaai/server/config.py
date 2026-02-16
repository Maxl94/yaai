"""Application settings loaded from environment variables and .env file."""

import logging
import os

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://aimon:changeme@localhost:5431/aimonitoring"
    database_url_sync: str = "postgresql://aimon:changeme@localhost:5431/aimonitoring"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

# Warn about default DB credentials
if "changeme" in settings.database_url:
    _is_prod = os.environ.get("ENVIRONMENT", "development").lower() in ("production", "prod")
    if _is_prod:
        raise RuntimeError(
            "FATAL: Database URL contains default credentials. Set DATABASE_URL with secure credentials."
        )
    logger.warning(
        "SECURITY WARNING: Database URL uses default credentials. "
        "Set POSTGRES_PASSWORD and DATABASE_URL for production."
    )
