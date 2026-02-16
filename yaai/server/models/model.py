"""SQLAlchemy models for ML models, versions, and schema fields."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yaai.schemas.model import DataType, FieldDirection
from yaai.server.database import Base, UUIDMixin

if TYPE_CHECKING:
    from yaai.server.models.inference import InferenceData, ReferenceData
    from yaai.server.models.job import JobConfig


class Model(UUIDMixin, Base):
    __tablename__ = "models"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    versions: Mapped[list[ModelVersion]] = relationship(back_populates="model", cascade="all, delete-orphan")


class ModelVersion(UUIDMixin, Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("model_id", "version", name="uq_model_version"),)

    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    model: Mapped[Model] = relationship(back_populates="versions")
    schema_fields: Mapped[list[SchemaField]] = relationship(
        back_populates="model_version", cascade="all, delete-orphan"
    )
    inferences: Mapped[list[InferenceData]] = relationship(back_populates="model_version", cascade="all, delete-orphan")
    reference_data: Mapped[list[ReferenceData]] = relationship(
        back_populates="model_version", cascade="all, delete-orphan"
    )
    job_configs: Mapped[list[JobConfig]] = relationship(back_populates="model_version", cascade="all, delete-orphan")

    @property
    def schema_field_count(self) -> int:
        return len(self.schema_fields) if self.schema_fields else 0


class SchemaField(UUIDMixin, Base):
    __tablename__ = "schema_fields"
    __table_args__ = (UniqueConstraint("model_version_id", "direction", "field_name", name="uq_schema_field"),)

    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[FieldDirection] = mapped_column(Enum(FieldDirection), nullable=False)
    field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[DataType] = mapped_column(Enum(DataType), nullable=False)
    drift_metric: Mapped[str | None] = mapped_column(String(50), nullable=True)
    alert_threshold: Mapped[float | None] = mapped_column(nullable=True)

    model_version: Mapped[ModelVersion] = relationship(back_populates="schema_fields")
