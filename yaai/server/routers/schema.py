"""Router for schema inference and validation operations."""

from fastapi import APIRouter, Depends

from yaai.schemas.model import (
    BatchValidationResult,
    InferSchemaBatchRequest,
    InferSchemaRequest,
    InferSchemaResponse,
    ValidateSchemaBatchRequest,
    ValidateSchemaRequest,
)
from yaai.server.auth.dependencies import require_auth
from yaai.server.services.schema_helpers import (
    infer_fields_from_sample,
    merge_inferred_schemas,
    validate_record,
)

router = APIRouter(prefix="/schema", tags=["schema"], dependencies=[Depends(require_auth)])


# -- Infer endpoints --


@router.post("/infer", response_model=dict)
async def infer_schema(data: InferSchemaRequest):
    """Infer schema fields from a single sample inference payload."""
    fields = infer_fields_from_sample(data.sample)
    return {"data": InferSchemaResponse(schema_fields=fields)}


@router.post("/infer/batch", response_model=dict)
async def infer_schema_batch(data: InferSchemaBatchRequest):
    """Infer schema fields from multiple samples, merged into one unified schema.

    Type conflicts (e.g. a field is numerical in one sample and categorical
    in another) are resolved by defaulting to categorical.
    """
    fields = merge_inferred_schemas(data.samples)
    return {"data": InferSchemaResponse(schema_fields=fields)}


# -- Validate endpoints --


@router.post("/validate", response_model=dict)
async def validate_schema(data: ValidateSchemaRequest):
    """Validate a single inference record against an inline schema."""
    result = validate_record(data.schema_fields, data.inputs, data.outputs)
    return {"data": result}


@router.post("/validate/batch", response_model=dict)
async def validate_schema_batch(data: ValidateSchemaBatchRequest):
    """Validate multiple inference records against an inline schema.

    Returns summary counts and per-field details for invalid records only.
    """
    total = len(data.records)
    valid_count = 0
    invalid_records: list[dict] = []

    for idx, record in enumerate(data.records):
        inputs = record.get("inputs", {})
        outputs = record.get("outputs", {})
        result = validate_record(data.schema_fields, inputs, outputs)
        if result.valid:
            valid_count += 1
        else:
            invalid_records.append(
                {
                    "index": idx,
                    "valid": False,
                    "fields": [f.model_dump(exclude_none=True) for f in result.fields if f.status != "ok"],
                }
            )

    return {
        "data": BatchValidationResult(
            total=total,
            valid=valid_count,
            invalid=total - valid_count,
            records=invalid_records,
        )
    }
