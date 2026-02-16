"""Shared helpers for schema inference and validation."""

from __future__ import annotations

from typing import Any

from yaai.schemas.model import (
    DataType,
    FieldDirection,
    FieldValidationResult,
    SchemaFieldCreate,
    ValidationResult,
)


def infer_data_type(value: Any) -> DataType:
    """Infer DataType from a Python value."""
    if isinstance(value, bool):
        return DataType.CATEGORICAL
    if isinstance(value, (int, float)):
        return DataType.NUMERICAL
    if isinstance(value, str):
        return DataType.CATEGORICAL
    return DataType.NUMERICAL


def infer_fields_from_sample(sample: dict[str, dict]) -> list[SchemaFieldCreate]:
    """Infer schema fields from a single sample with inputs/outputs."""
    fields: list[SchemaFieldCreate] = []
    for direction_key in ("inputs", "outputs"):
        direction = FieldDirection.INPUT if direction_key == "inputs" else FieldDirection.OUTPUT
        sample_fields = sample.get(direction_key, {})
        for key, value in sample_fields.items():
            fields.append(
                SchemaFieldCreate(
                    direction=direction,
                    field_name=key,
                    data_type=infer_data_type(value),
                    drift_metric=None,
                    alert_threshold=None,
                )
            )
    return fields


def merge_inferred_schemas(samples: list[dict[str, dict]]) -> list[SchemaFieldCreate]:
    """Infer schema from multiple samples, merging into one unified schema.

    Type conflict resolution: if a field appears as both numerical and
    categorical across samples, it defaults to categorical (safer).
    """
    # key: (direction, field_name) -> set of DataTypes seen
    seen: dict[tuple[FieldDirection, str], set[DataType]] = {}

    for sample in samples:
        for direction_key in ("inputs", "outputs"):
            direction = FieldDirection.INPUT if direction_key == "inputs" else FieldDirection.OUTPUT
            sample_fields = sample.get(direction_key, {})
            for key, value in sample_fields.items():
                dt = infer_data_type(value)
                composite_key = (direction, key)
                if composite_key not in seen:
                    seen[composite_key] = set()
                seen[composite_key].add(dt)

    fields: list[SchemaFieldCreate] = []
    for (direction, field_name), types in seen.items():
        # If conflicting types, default to categorical
        data_type = DataType.CATEGORICAL if len(types) > 1 else next(iter(types))
        fields.append(
            SchemaFieldCreate(
                direction=direction,
                field_name=field_name,
                data_type=data_type,
                drift_metric=None,
                alert_threshold=None,
            )
        )
    return fields


def validate_record(
    schema_fields: list[SchemaFieldCreate],
    inputs: dict,
    outputs: dict,
) -> ValidationResult:
    """Validate a single inference record against schema fields.

    Returns a ValidationResult with per-field status instead of raising.
    """
    field_results: list[FieldValidationResult] = []
    all_ok = True

    for field in schema_fields:
        data = inputs if field.direction == FieldDirection.INPUT else outputs
        result = _validate_single_field(field, data)
        field_results.append(result)
        if result.status != "ok":
            all_ok = False

    return ValidationResult(valid=all_ok, fields=field_results)


def _validate_single_field(field: SchemaFieldCreate, data: dict) -> FieldValidationResult:
    """Validate a single field against data, returning a result object."""
    if field.field_name not in data:
        return FieldValidationResult(
            field_name=field.field_name,
            direction=field.direction,
            status="missing",
            error=f"Missing required field: {field.field_name}",
        )

    value = data[field.field_name]
    if value is None:
        return FieldValidationResult(
            field_name=field.field_name,
            direction=field.direction,
            status="ok",
        )

    if field.data_type == DataType.NUMERICAL and not isinstance(value, (int, float)):
        return FieldValidationResult(
            field_name=field.field_name,
            direction=field.direction,
            status="error",
            error=f"Expected numerical, got {type(value).__name__}",
        )

    if field.data_type == DataType.CATEGORICAL and not isinstance(value, (str, bool)):
        return FieldValidationResult(
            field_name=field.field_name,
            direction=field.direction,
            status="error",
            error=f"Expected categorical (string/bool), got {type(value).__name__}",
        )

    return FieldValidationResult(
        field_name=field.field_name,
        direction=field.direction,
        status="ok",
    )
