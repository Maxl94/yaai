"""Pydantic schemas for model and version API requests/responses."""

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DataType(enum.StrEnum):
    NUMERICAL = "numerical"
    CATEGORICAL = "categorical"


class FieldDirection(enum.StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class SchemaFieldCreate(BaseModel):
    direction: FieldDirection
    field_name: str
    data_type: DataType
    drift_metric: str | None = None
    alert_threshold: float | None = Field(None, gt=0)


class SchemaFieldRead(SchemaFieldCreate):
    id: uuid.UUID

    model_config = {"from_attributes": True}


class SchemaFieldThresholdUpdate(BaseModel):
    alert_threshold: float | None = Field(None, gt=0)


class ModelVersionCreate(BaseModel):
    version: str
    description: str | None = None
    schema_fields: list[SchemaFieldCreate] = Field(..., alias="schema", min_length=1)
    keep_previous_active: bool = False

    model_config = {"populate_by_name": True}


class ModelVersionRead(BaseModel):
    id: uuid.UUID
    model_id: uuid.UUID
    version: str
    description: str | None
    is_active: bool
    created_at: datetime
    schema_fields: list[SchemaFieldRead] = []

    model_config = {"from_attributes": True}


class ModelVersionSummary(BaseModel):
    id: uuid.UUID
    version: str
    is_active: bool
    created_at: datetime
    schema_field_count: int = 0

    model_config = {"from_attributes": True}


class ModelVersionUpdate(BaseModel):
    description: str | None = None
    is_active: bool | None = None


class ModelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class ModelRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    versions: list[ModelVersionSummary] = []

    model_config = {"from_attributes": True}


class ModelSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    active_version: ModelVersionSummary | None = None
    total_inferences: int = 0

    model_config = {"from_attributes": True}


class ModelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class InferSchemaRequest(BaseModel):
    """Request body for schema inference from a single sample."""

    sample: dict[str, dict]


class InferSchemaBatchRequest(BaseModel):
    """Request body for schema inference from multiple samples (merged result)."""

    samples: list[dict[str, dict]] = Field(..., min_length=1, max_length=10000)


class InferSchemaResponse(BaseModel):
    """Response containing inferred schema fields."""

    schema_fields: list[SchemaFieldCreate]


# -- Schema validation request/response schemas --


class ValidateSchemaRequest(BaseModel):
    """Validate a single inference record against an inline schema."""

    schema_fields: list[SchemaFieldCreate] = Field(..., alias="schema", min_length=1)
    inputs: dict
    outputs: dict

    model_config = {"populate_by_name": True}


class ValidateSchemaBatchRequest(BaseModel):
    """Validate multiple inference records against an inline schema."""

    schema_fields: list[SchemaFieldCreate] = Field(..., alias="schema", min_length=1)
    records: list[dict] = Field(..., min_length=1, max_length=10000)

    model_config = {"populate_by_name": True}


class ValidateModelVersionRequest(BaseModel):
    """Validate a single inference record against a model version's schema."""

    inputs: dict
    outputs: dict


class ValidateModelVersionBatchRequest(BaseModel):
    """Validate multiple inference records against a model version's schema."""

    records: list[dict] = Field(..., min_length=1, max_length=10000)


class FieldValidationResult(BaseModel):
    """Validation result for a single schema field."""

    field_name: str
    direction: FieldDirection
    status: str  # "ok", "error", "missing"
    error: str | None = None


class ValidationResult(BaseModel):
    """Validation result for a single inference record."""

    valid: bool
    fields: list[FieldValidationResult]


class BatchValidationResult(BaseModel):
    """Validation result for a batch of inference records."""

    total: int
    valid: int
    invalid: int
    records: list[dict]  # only invalid records: {"index": int, "valid": false, "fields": [...]}
