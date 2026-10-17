import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.auth.dependencies import CurrentIdentity, check_version_read_access, require_auth
from yaai.server.database import get_db
from yaai.server.schemas.dashboard import DashboardPanel, DashboardResponse
from yaai.server.services.comparison_service import ComparisonService
from yaai.server.services.dashboard_service import DashboardService

router = APIRouter(tags=["dashboard"], dependencies=[Depends(require_auth)])


@router.get("/models/{model_id}/versions/{version_id}/dashboard")
async def get_dashboard(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await check_version_read_access(model_id, version_id, identity, db)
    svc = DashboardService(db)
    panels = await svc.get_dashboard(version_id, from_ts, to_ts)
    return {
        "data": DashboardResponse(
            model_version_id=version_id,
            time_range={"from": from_ts, "to": to_ts},
            panels=[DashboardPanel.model_validate(p) for p in panels],
        ),
    }


@router.get("/models/{model_id}/versions/{version_id}/dashboard/compare")
async def compare_dashboard(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    mode: str = Query("time_window", pattern="^(time_window|vs_reference|vs_version)$"),
    other_model_id: uuid.UUID | None = Query(None),
    other_version_id: uuid.UUID | None = Query(None),
    from_a: datetime | None = Query(None),
    to_a: datetime | None = Query(None),
    from_b: datetime | None = Query(None),
    to_b: datetime | None = Query(None),
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    await check_version_read_access(model_id, version_id, identity, db)
    svc = ComparisonService(db)
    schema_diff: list[dict] = []
    if mode == "vs_version":
        if not (other_model_id and other_version_id and from_a and to_a and from_b and to_b):
            raise HTTPException(
                status_code=422,
                detail="other_model_id, other_version_id, from_a, to_a, from_b, to_b are required for vs_version mode",
            )
        await check_version_read_access(other_model_id, other_version_id, identity, db)
        panels, schema_diff = await svc.compare_versions(version_id, other_version_id, from_a, to_a, from_b, to_b)
    elif mode == "vs_reference":
        if not from_a or not to_a:
            raise HTTPException(status_code=422, detail="from_a and to_a are required for vs_reference mode")
        panels = await svc.compare_vs_reference(version_id, from_a, to_a)
    else:
        if not from_a or not to_a or not from_b or not to_b:
            raise HTTPException(status_code=422, detail="from_a, to_a, from_b, to_b are required for time_window mode")
        panels = await svc.compare_time_windows(version_id, from_a, to_a, from_b, to_b)

    return {"data": {"model_version_id": str(version_id), "panels": panels, "schema_diff": schema_diff}}
