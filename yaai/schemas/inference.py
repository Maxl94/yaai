"""Pydantic schemas for inference, reference data, and ground truth."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class InferenceCreate(BaseModel):
    model_version_id: uuid.UUID
    inputs: dict
    outputs: dict
    timestamp: datetime | None = None


class InferenceRead(BaseModel):
    id: uuid.UUID
    model_version_id: uuid.UUID
    timestamp: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class InferenceBatchCreate(BaseModel):
    model_version_id: uuid.UUID
    records: list[dict] = Field(..., max_length=10000)


class InferenceBatchResult(BaseModel):
    ingested: int
    failed: int
    errors: list[str] = []


class ReferenceDataUpload(BaseModel):
    records: list[dict] = Field(..., max_length=50000)


class ReferenceDataResult(BaseModel):
    ingested: int
    model_version_id: uuid.UUID


class GroundTruthCreate(BaseModel):
    inference_id: uuid.UUID
    label: dict
    timestamp: datetime | None = None
