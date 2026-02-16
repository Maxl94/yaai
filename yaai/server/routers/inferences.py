import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.schemas.common import PaginationMeta
from yaai.schemas.inference import (
    GroundTruthCreate,
    InferenceBatchCreate,
    InferenceBatchResult,
    InferenceCreate,
    InferenceRead,
    ReferenceDataResult,
    ReferenceDataUpload,
)
from yaai.server.auth.dependencies import (
    CurrentIdentity,
    check_model_read_access,
    check_model_write_access,
    require_auth,
    require_model_write,
    resolve_model_id_from_version,
)
from yaai.server.database import get_db
from yaai.server.models.inference import InferenceData
from yaai.server.models.model import ModelVersion
from yaai.server.rate_limit import limiter
from yaai.server.services.inference_service import InferenceService

router = APIRouter(tags=["inferences"], dependencies=[Depends(require_auth)])


@router.post("/inferences", status_code=201)
@limiter.limit("60/minute")
async def create_inference(
    request: Request,
    data: InferenceCreate,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_id = await resolve_model_id_from_version(data.model_version_id, db)
    await check_model_write_access(model_id, identity, db)
    svc = InferenceService(db)
    inference = await svc.create_inference(data.model_version_id, data.inputs, data.outputs, data.timestamp)
    return {"data": InferenceRead.model_validate(inference)}


@router.post("/inferences/batch", status_code=201)
@limiter.limit("60/minute")
async def create_inference_batch(
    request: Request,
    data: InferenceBatchCreate,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_id = await resolve_model_id_from_version(data.model_version_id, db)
    await check_model_write_access(model_id, identity, db)
    svc = InferenceService(db)
    result = await svc.create_inference_batch(data.model_version_id, data.records)
    return {"data": InferenceBatchResult(**result)}


@router.get("/inferences")
async def list_inferences(
    model_version_id: uuid.UUID,
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_id = await resolve_model_id_from_version(model_version_id, db)
    await check_model_read_access(model_id, identity, db)
    svc = InferenceService(db)
    inferences, total = await svc.list_inferences(model_version_id, from_ts, to_ts, page, page_size)
    return {
        "data": [InferenceRead.model_validate(i) for i in inferences],
        "meta": PaginationMeta(total=total, page=page, page_size=page_size),
    }


@router.get("/models/{model_id}/versions/{version_id}/inference-volume")
async def get_inference_volume(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    bucket: str = Query("day", pattern="^(hour|day|week|month)$"),
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await check_model_read_access(model_id, identity, db)
    svc = InferenceService(db)
    volume = await svc.get_inference_volume(version_id, bucket, from_ts, to_ts)
    return {"data": volume}


@router.post("/models/{model_id}/versions/{version_id}/reference-data", status_code=201)
@limiter.limit("30/minute")
async def upload_reference_data(
    request: Request,
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    data: ReferenceDataUpload,
    _identity: CurrentIdentity = Depends(require_model_write),
    db: AsyncSession = Depends(get_db),
):
    svc = InferenceService(db)
    count = await svc.upload_reference_data(model_id, version_id, data.records)
    return {"data": ReferenceDataResult(ingested=count, model_version_id=version_id)}


@router.post("/ground-truth", status_code=201)
async def create_ground_truth(
    data: GroundTruthCreate,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    # Resolve model_id from inference → version → model
    stmt = (
        select(ModelVersion.model_id)
        .join(InferenceData, InferenceData.model_version_id == ModelVersion.id)
        .where(InferenceData.id == data.inference_id)
    )
    result = await db.execute(stmt)
    model_id = result.scalar_one_or_none()
    if model_id is None:
        raise HTTPException(status_code=404, detail="Inference not found")
    await check_model_write_access(model_id, identity, db)

    svc = InferenceService(db)
    gt = await svc.create_ground_truth(data.inference_id, data.label, data.timestamp)
    return {"data": {"id": gt.id, "inference_id": gt.inference_id}}
