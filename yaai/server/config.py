"""Application settings loaded from environment variables and .env file."""

import logging
import os
import re

from pydantic import computed_field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    base_url: str = "http://localhost:8000"
    database_url: str = "postgresql+asyncpg://aimon:changeme@localhost:5431/aimonitoring"

    # Maximum records sampled for drift detection and distribution comparison.
    # Statistical tests (KS, PSI, chi-squared) give reliable results well below 10k samples.
    # Override via DRIFT_MAX_SAMPLES env var.
    drift_max_samples: int = 10_000

    # Reference data cap – uploads exceeding this many records are rejected (HTTP 422).
    # Override via REFERENCE_DATA_MAX_RECORDS env var.
    reference_data_max_records: int = 50_000

    # Maximum rows fed into the dashboard histogram/stats computation.
    # The most recent N records are used so the distribution reflects current behaviour.
    # Histograms are statistically stable well below 100k samples.
    # Override via DASHBOARD_MAX_SAMPLES env var.
    dashboard_max_samples: int = 50_000

    # Cloud SQL Connector (opt-in: set CLOUD_SQL_INSTANCE to enable)
    cloud_sql_instance: str | None = None
    cloud_sql_ip_type: str = "public"
    cloud_sql_iam_auth: bool = True
    cloud_sql_database: str = "aimonitoring"
    cloud_sql_user: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_sync(self) -> str:
        """Derive sync DB URL from async URL by stripping the +asyncpg driver suffix."""
        return re.sub(r"\+asyncpg", "", self.database_url)


settings = Settings()

# Warn about default DB credentials (skip when Cloud SQL connector is used)
if "changeme" in settings.database_url and not settings.cloud_sql_instance:
    _is_prod = os.environ.get("ENVIRONMENT", "development").lower() in ("production", "prod")
    if _is_prod:
        raise RuntimeError(
            "FATAL: Database URL contains default credentials. Set DATABASE_URL with secure credentials."
        )
    logger.warning(
        "SECURITY WARNING: Database URL uses default credentials. "
        "Set POSTGRES_PASSWORD and DATABASE_URL for production."
    )
