import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.schemas.common import PaginationMeta
from yaai.schemas.model import (
    BatchValidationResult,
    ModelCreate,
    ModelRead,
    ModelSummary,
    ModelUpdate,
    ModelVersionCreate,
    ModelVersionRead,
    ModelVersionUpdate,
    SchemaFieldCreate,
    SchemaFieldRead,
    SchemaFieldThresholdUpdate,
    ValidateModelVersionBatchRequest,
    ValidateModelVersionRequest,
)
from yaai.server.auth.dependencies import (
    CurrentIdentity,
    check_model_read_access,
    get_accessible_model_ids,
    get_project_role,
    has_global_access,
    require_auth,
    require_model_write,
    require_owner,
)
from yaai.server.database import get_db
from yaai.server.models.auth import ModelAccess
from yaai.server.models.project import DEFAULT_PROJECT_NAME, WRITE_ROLES
from yaai.server.services.model_service import ModelService
from yaai.server.services.project_service import ProjectService, get_or_create_default_project
from yaai.server.services.schema_helpers import validate_record

router = APIRouter(prefix="/models", tags=["models"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_models(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    project_id: uuid.UUID | None = None,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_ids = await get_accessible_model_ids(identity)
    svc = ModelService(db)
    summaries, total = await svc.list_models(page, page_size, search, model_ids=model_ids, project_id=project_id)
    return {
        "data": [ModelSummary(**s) for s in summaries],
        "meta": PaginationMeta(total=total, page=page, page_size=page_size),
    }


async def _authorize_model_creation(identity: CurrentIdentity, project_id: uuid.UUID, db: AsyncSession) -> bool:
    """Authorize model creation in a project.

    Global owners and editors/owners of the project are allowed; service accounts may also use the default project.

    Returns:
        True if a service account was allowed only through the default-project fallback (it then needs a
        ModelAccess grant), False if access derives from global ownership or a project membership.

    Raises:
        HTTPException: 403 if the identity may not create models in the project.
    """
    if has_global_access(identity):
        return False
    if await get_project_role(identity, project_id, db) in WRITE_ROLES:
        return False
    if identity.is_service_account:
        # Backward compatibility: service accounts without membership may create models in the default project
        project = await ProjectService(db).get_project(project_id)
        if project.name == DEFAULT_PROJECT_NAME:
            return True
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Service account cannot create models in this project"
        )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Editor access to the project required")


@router.post("", status_code=201)
async def create_model(
    data: ModelCreate,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create a model in ``project_id`` (default project if omitted)."""
    if data.project_id is None:
        project_id = (await get_or_create_default_project(db)).id
    else:
        project_id = (await ProjectService(db).get_project(data.project_id)).id
    needs_access_grant = await _authorize_model_creation(identity, project_id, db)

    svc = ModelService(db)
    model = await svc.create_model(data, project_id)

    # Only the backward-compat path grants a ModelAccess entry; membership-based access must stay revocable
    if needs_access_grant and identity.service_account_id:
        access = ModelAccess(
            model_id=model.id,
            service_account_id=uuid.UUID(identity.service_account_id),
        )
        db.add(access)
        await db.commit()

    return {"data": ModelRead.model_validate(model)}


@router.get("/{model_id}")
async def get_model(
    model_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await check_model_read_access(model_id, identity, db)
    svc = ModelService(db)
    model = await svc.get_model(model_id)
    return {"data": ModelRead.model_validate(model)}


@router.put("/{model_id}")
@router.patch("/{model_id}")
async def update_model(
    model_id: uuid.UUID,
    data: ModelUpdate,
    identity: CurrentIdentity = Depends(require_model_write),
    db: AsyncSession = Depends(get_db),
):
    """Update name/description (editors) or move the model to another project via ``project_id`` (global owners)."""
    svc = ModelService(db)
    if data.project_id is not None and not has_global_access(identity):
        current = await svc.get_model(model_id)
        if data.project_id != current.project_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Only owners can move models between projects"
            )
    model = await svc.update_model(model_id, data)
    return {"data": ModelRead.model_validate(model)}


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: uuid.UUID,
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    svc = ModelService(db)
    await svc.delete_model(model_id)


@router.post("/{model_id}/versions", status_code=201)
async def create_version(
    model_id: uuid.UUID,
    data: ModelVersionCreate,
    _identity: CurrentIdentity = Depends(require_model_write),
    db: AsyncSession = Depends(get_db),
):
    svc = ModelService(db)
    version = await svc.create_version(model_id, data)
    return {"data": ModelVersionRead.model_validate(version)}


@router.get("/{model_id}/versions/{version_id}")
async def get_version(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await check_model_read_access(model_id, identity, db)
    svc = ModelService(db)
    version = await svc.get_version(model_id, version_id)
    return {"data": ModelVersionRead.model_validate(version)}


@router.patch("/{model_id}/versions/{version_id}")
async def update_version(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    data: ModelVersionUpdate,
    _identity: CurrentIdentity = Depends(require_model_write),
    db: AsyncSession = Depends(get_db),
):
    svc = ModelService(db)
    version = await svc.update_version(model_id, version_id, data)
    return {"data": ModelVersionRead.model_validate(version)}


@router.put("/{model_id}/versions/{version_id}/schema")
async def overwrite_schema(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    schema: list[SchemaFieldCreate],
    _identity: CurrentIdentity = Depends(require_model_write),
    db: AsyncSession = Depends(get_db),
):
    svc = ModelService(db)
    version = await svc.overwrite_schema(model_id, version_id, schema)
    return {"data": ModelVersionRead.model_validate(version)}


@router.patch("/{model_id}/versions/{version_id}/fields/{field_id}/threshold")
async def update_field_threshold(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    field_id: uuid.UUID,
    data: SchemaFieldThresholdUpdate,
    _identity: CurrentIdentity = Depends(require_model_write),
    db: AsyncSession = Depends(get_db),
):
    svc = ModelService(db)
    field = await svc.update_field_threshold(model_id, version_id, field_id, data.alert_threshold)
    return {"data": SchemaFieldRead.model_validate(field)}


@router.post("/{model_id}/versions/{version_id}/schema/validate")
async def validate_version_schema(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    data: ValidateModelVersionRequest,
    _identity: CurrentIdentity = Depends(require_model_write),
    db: AsyncSession = Depends(get_db),
):
    """Validate a single inference record against the model version's schema."""
    svc = ModelService(db)
    version = await svc.get_version(model_id, version_id)
    schema_fields = [
        SchemaFieldCreate(
            direction=f.direction,
            field_name=f.field_name,
            data_type=f.data_type,
            drift_metric=f.drift_metric,
            alert_threshold=f.alert_threshold,
        )
        for f in version.schema_fields
    ]
    result = validate_record(schema_fields, data.inputs, data.outputs)
    return {"data": result}


@router.post("/{model_id}/versions/{version_id}/schema/validate/batch")
async def validate_version_schema_batch(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    data: ValidateModelVersionBatchRequest,
    _identity: CurrentIdentity = Depends(require_model_write),
    db: AsyncSession = Depends(get_db),
):
    """Validate multiple inference records against the model version's schema.

    Returns summary counts and per-field details for invalid records only.
    """
    svc = ModelService(db)
    version = await svc.get_version(model_id, version_id)
    schema_fields = [
        SchemaFieldCreate(
            direction=f.direction,
            field_name=f.field_name,
            data_type=f.data_type,
            drift_metric=f.drift_metric,
            alert_threshold=f.alert_threshold,
        )
        for f in version.schema_fields
    ]

    total = len(data.records)
    valid_count = 0
    invalid_records: list[dict] = []

    for idx, record in enumerate(data.records):
        inputs = record.get("inputs", {})
        outputs = record.get("outputs", {})
        result = validate_record(schema_fields, inputs, outputs)
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
