"""SQLAlchemy models for inference data, reference data, and ground truth."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yaai.server.database import Base, UUIDMixin

if TYPE_CHECKING:
    from yaai.server.models.model import ModelVersion


class InferenceData(UUIDMixin, Base):
    __tablename__ = "inference_data"
    __table_args__ = (Index("ix_inference_version_timestamp", "model_version_id", "timestamp"),)

    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False
    )
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    outputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    model_version: Mapped[ModelVersion] = relationship(back_populates="inferences")


class ReferenceData(UUIDMixin, Base):
    __tablename__ = "reference_data"

    model_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False
    )
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    outputs: Mapped[dict] = mapped_column(JSON, nullable=False)

    model_version: Mapped[ModelVersion] = relationship(back_populates="reference_data")


class GroundTruth(UUIDMixin, Base):
    __tablename__ = "ground_truth"

    inference_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inference_data.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    label: Mapped[dict] = mapped_column(JSON, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
