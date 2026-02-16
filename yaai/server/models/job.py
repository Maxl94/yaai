"""SQLAlchemy models for drift detection jobs, runs, results, and notifications."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yaai.server.database import Base, UUIDMixin

if TYPE_CHECKING:
    from yaai.server.models.model import ModelVersion


class ComparisonType(enum.StrEnum):
    VS_REFERENCE = "vs_reference"
    ROLLING_WINDOW = "rolling_window"


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NotificationSeverity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class JobConfig(UUIDMixin, Base):
    __tablename__ = "job_configs"

    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schedule: Mapped[str] = mapped_column(String(100), nullable=False)
    comparison_type: Mapped[ComparisonType] = mapped_column(Enum(ComparisonType), nullable=False)
    window_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    min_samples: Mapped[int] = mapped_column(Integer, default=200)
    is_active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    model_version: Mapped[ModelVersion] = relationship(back_populates="job_configs")
    runs: Mapped[list[JobRun]] = relationship(back_populates="job_config", cascade="all, delete-orphan")


class JobRun(UUIDMixin, Base):
    __tablename__ = "job_runs"

    job_config_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_configs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False, default=JobStatus.PENDING)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    job_config: Mapped[JobConfig] = relationship(back_populates="runs")
    drift_results: Mapped[list[DriftResult]] = relationship(back_populates="job_run", cascade="all, delete-orphan")


class DriftResult(UUIDMixin, Base):
    __tablename__ = "drift_results"
    __table_args__ = (Index("ix_drift_run_field", "job_run_id", "schema_field_id"),)

    job_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job_runs.id", ondelete="CASCADE"), nullable=False)
    schema_field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schema_fields.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(50), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    is_drifted: Mapped[bool] = mapped_column(nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    job_run: Mapped[JobRun] = relationship(back_populates="drift_results")


class Notification(UUIDMixin, Base):
    __tablename__ = "notifications"

    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False
    )
    drift_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drift_results.id", ondelete="SET NULL"), nullable=True
    )
    severity: Mapped[NotificationSeverity] = mapped_column(Enum(NotificationSeverity), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
