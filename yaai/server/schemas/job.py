"""Pydantic schemas for job configs, drift results, and notifications."""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, field_validator

from yaai.server.models.job import ComparisonType, JobStatus, NotificationSeverity


class _Unset(Enum):
    """Sentinel to distinguish 'not provided' from an explicit None."""

    UNSET = "UNSET"


UNSET = _Unset.UNSET


class JobConfigRead(BaseModel):
    id: uuid.UUID
    model_version_id: uuid.UUID
    name: str
    schedule: str
    comparison_type: ComparisonType
    window_size: str | None
    min_samples: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class JobConfigUpdate(BaseModel):
    name: str | None = None
    schedule: str | None = None
    comparison_type: ComparisonType | None = None
    window_size: str | None | _Unset = UNSET
    min_samples: int | None = None
    is_active: bool | None = None

    @field_validator("schedule")
    @classmethod
    def validate_cron_schedule(cls, v: str | None) -> str | None:
        """Validate that the schedule is a valid cron expression, if provided."""
        if v is None:
            return v
        from apscheduler.triggers.cron import CronTrigger

        try:
            CronTrigger.from_crontab(v)
        except ValueError as e:
            raise ValueError(f"Invalid cron expression: {e}") from e
        return v


class JobRunRead(BaseModel):
    id: uuid.UUID
    job_config_id: uuid.UUID
    status: JobStatus
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None

    model_config = {"from_attributes": True}


class DriftResultRead(BaseModel):
    id: uuid.UUID
    job_run_id: uuid.UUID
    schema_field_id: uuid.UUID
    field_name: str  # From schema_field.field_name
    metric_name: str
    score: float  # Alias for metric_value
    threshold: float  # From job config or default
    is_drifted: bool
    details: dict | None
    created_at: datetime  # From job_run.started_at

    model_config = {"from_attributes": True}


class DriftOverviewItem(BaseModel):
    model_id: uuid.UUID
    model_name: str
    model_description: str | None
    version_id: uuid.UUID
    version: str
    total_inferences: int
    total_fields: int
    drifted_fields: int
    health_percentage: int
    last_check: datetime | None
    results: list[DriftResultRead]


class NotificationRead(BaseModel):
    id: uuid.UUID
    model_version_id: uuid.UUID
    drift_result_id: uuid.UUID | None
    severity: NotificationSeverity
    message: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
