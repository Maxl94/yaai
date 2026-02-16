import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.schemas.common import PaginationMeta
from yaai.server.auth.dependencies import (
    CurrentIdentity,
    check_model_read_access,
    check_model_write_access,
    get_accessible_model_ids,
    require_auth,
    resolve_model_id_from_job,
)
from yaai.server.database import get_db
from yaai.server.schemas.job import (
    DriftResultRead,
    JobConfigRead,
    JobConfigUpdate,
    JobRunRead,
    NotificationRead,
)
from yaai.server.services.drift_service import DriftService
from yaai.server.services.job_service import JobService

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_auth)])


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_id = await resolve_model_id_from_job(job_id, db)
    await check_model_read_access(model_id, identity, db)
    svc = JobService(db)
    job = await svc.get_job(job_id)
    return {"data": JobConfigRead.model_validate(job)}


@router.get("/models/{model_id}/versions/{version_id}/jobs")
async def list_jobs_for_version(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await check_model_read_access(model_id, identity, db)
    svc = JobService(db)
    jobs = await svc.list_jobs(version_id)
    return {"data": [JobConfigRead.model_validate(j) for j in jobs]}


@router.get("/jobs")
async def list_all_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List all jobs across all models/versions."""
    model_ids = await get_accessible_model_ids(identity, db)
    svc = JobService(db)
    jobs, total = await svc.list_all_jobs(page, page_size, model_ids=model_ids)
    return {
        "data": [JobConfigRead.model_validate(j) for j in jobs],
        "meta": PaginationMeta(total=total, page=page, page_size=page_size),
    }


@router.patch("/jobs/{job_id}")
async def update_job(
    job_id: uuid.UUID,
    data: JobConfigUpdate,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_id = await resolve_model_id_from_job(job_id, db)
    await check_model_write_access(model_id, identity, db)
    svc = JobService(db)
    job = await svc.update_job(job_id, data)
    return {"data": JobConfigRead.model_validate(job)}


@router.get("/jobs/{job_id}/runs")
async def list_job_runs(
    job_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_id = await resolve_model_id_from_job(job_id, db)
    await check_model_read_access(model_id, identity, db)
    svc = JobService(db)
    runs, total = await svc.list_job_runs(job_id, page, page_size)
    return {
        "data": [JobRunRead.model_validate(r) for r in runs],
        "meta": PaginationMeta(total=total, page=page, page_size=page_size),
    }


@router.post("/jobs/{job_id}/trigger", status_code=201)
async def trigger_job(
    job_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_id = await resolve_model_id_from_job(job_id, db)
    await check_model_write_access(model_id, identity, db)
    svc = DriftService(db)
    run = await svc.trigger_job(job_id)
    return {"data": JobRunRead.model_validate(run)}


@router.post("/jobs/{job_id}/backfill", status_code=201)
async def backfill_job(
    job_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Run drift detection for all historical time windows of this job."""
    model_id = await resolve_model_id_from_job(job_id, db)
    await check_model_write_access(model_id, identity, db)
    drift_svc = DriftService(db)
    runs = await drift_svc.backfill_job(job_id)
    return {"data": {"runs_created": len(runs)}}


@router.get("/drift-overview")
async def drift_overview(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Overview of drift status for all models with active versions."""
    model_ids = await get_accessible_model_ids(identity, db)
    svc = JobService(db)
    items, total = await svc.get_drift_overview(page, page_size, model_ids=model_ids)
    return {
        "data": items,
        "meta": PaginationMeta(total=total, page=page, page_size=page_size),
    }


@router.get("/models/{model_id}/versions/{version_id}/drift-results")
async def list_drift_results(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    is_drifted: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await check_model_read_access(model_id, identity, db)
    svc = JobService(db)
    results, total = await svc.list_drift_results(version_id, is_drifted, page, page_size)
    return {
        "data": [DriftResultRead.model_validate(r) for r in results],
        "meta": PaginationMeta(total=total, page=page, page_size=page_size),
    }


@router.get("/notifications")
async def list_notifications(
    is_read: bool | None = None,
    model_version_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_ids = await get_accessible_model_ids(identity, db)
    svc = JobService(db)
    notifications, total = await svc.list_notifications(is_read, model_version_id, page, page_size, model_ids=model_ids)
    return {
        "data": [NotificationRead.model_validate(n) for n in notifications],
        "meta": PaginationMeta(total=total, page=page, page_size=page_size),
    }


@router.patch("/notifications/{notification_id}")
async def mark_notification_read(
    notification_id: uuid.UUID,
    _identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    svc = JobService(db)
    notification = await svc.mark_notification_read(notification_id)
    return {"data": NotificationRead.model_validate(notification)}


@router.post("/notifications/mark-all-read")
async def mark_all_read(
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    model_ids = await get_accessible_model_ids(identity, db)
    svc = JobService(db)
    count = await svc.mark_all_notifications_read(model_ids=model_ids)
    return {"data": {"marked_read": count}}
