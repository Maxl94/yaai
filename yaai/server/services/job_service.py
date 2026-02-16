import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yaai.server.drift.registry import get_metric
from yaai.server.models.inference import InferenceData
from yaai.server.models.job import DriftResult, JobConfig, JobRun, Notification
from yaai.server.models.model import Model, ModelVersion, SchemaField
from yaai.server.scheduler import register_job
from yaai.server.schemas.job import UNSET, JobConfigUpdate
from yaai.server.services.utils.pagination import paginate_query


@dataclass
class DriftResultEnriched:
    """Enriched drift result with resolved field name and threshold."""

    id: uuid.UUID
    job_run_id: uuid.UUID
    schema_field_id: uuid.UUID
    field_name: str
    metric_name: str
    score: float
    threshold: float
    is_drifted: bool
    details: dict | None
    created_at: datetime


class JobService:
    """Manages drift detection job configuration, execution history, and notifications."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _resolve_threshold(self, metric_name: str, field_threshold: float | None, data_type_value: str) -> float:
        """Resolve the effective threshold for a drift result."""
        if field_threshold is not None:
            return field_threshold
        metric = get_metric(metric_name, data_type_value)
        return metric.default_threshold

    def _build_enriched_result(
        self,
        drift_result: DriftResult,
        field_name: str,
        threshold: float,
        created_at: datetime,
    ) -> dict:
        """Build enriched drift result dictionary."""
        return {
            "id": drift_result.id,
            "job_run_id": drift_result.job_run_id,
            "schema_field_id": drift_result.schema_field_id,
            "field_name": field_name,
            "metric_name": drift_result.metric_name,
            "score": drift_result.metric_value,
            "threshold": threshold,
            "is_drifted": drift_result.is_drifted,
            "details": drift_result.details,
            "created_at": created_at,
        }

    async def list_jobs(self, model_version_id: uuid.UUID) -> list[JobConfig]:
        """List all jobs for a specific model version."""
        result = await self.db.execute(
            select(JobConfig)
            .where(JobConfig.model_version_id == model_version_id)
            .order_by(JobConfig.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_all_jobs(
        self, page: int = 1, page_size: int = 20, model_ids: list[uuid.UUID] | None = None
    ) -> tuple[list[JobConfig], int]:
        """List all jobs across all model versions with pagination."""
        query = select(JobConfig)
        if model_ids is not None:
            query = query.join(ModelVersion, JobConfig.model_version_id == ModelVersion.id).where(
                ModelVersion.model_id.in_(model_ids)
            )
        query = query.order_by(JobConfig.created_at.desc())
        return await paginate_query(self.db, query, page, page_size)

    async def get_job(self, job_id: uuid.UUID) -> JobConfig:
        result = await self.db.execute(select(JobConfig).where(JobConfig.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    async def update_job(self, job_id: uuid.UUID, data: JobConfigUpdate) -> JobConfig:
        """Update job configuration fields and re-register with the scheduler."""
        job = await self.get_job(job_id)
        if data.name is not None:
            job.name = data.name
        if data.schedule is not None:
            job.schedule = data.schedule
        if data.comparison_type is not None:
            job.comparison_type = data.comparison_type
        if data.window_size is not UNSET:
            job.window_size = data.window_size
        if data.min_samples is not None:
            job.min_samples = data.min_samples
        if data.is_active is not None:
            job.is_active = data.is_active
        await self.db.commit()
        await self.db.refresh(job)
        register_job(job)
        return job

    async def list_job_runs(self, job_id: uuid.UUID, page: int = 1, page_size: int = 20):
        """List execution history for a job with pagination."""
        query = select(JobRun).where(JobRun.job_config_id == job_id).order_by(JobRun.started_at.desc())
        return await paginate_query(self.db, query, page, page_size)

    async def list_drift_results(
        self,
        model_version_id: uuid.UUID,
        is_drifted: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[DriftResultEnriched], int]:
        """List drift results for a model version, enriched with field names and thresholds."""

        query = (
            select(
                DriftResult,
                SchemaField.field_name,
                SchemaField.alert_threshold,
                SchemaField.data_type,
                JobRun.started_at,
            )
            .join(JobRun, DriftResult.job_run_id == JobRun.id)
            .join(JobConfig, JobRun.job_config_id == JobConfig.id)
            .join(SchemaField, DriftResult.schema_field_id == SchemaField.id)
            .where(JobConfig.model_version_id == model_version_id)
        )
        if is_drifted is not None:
            query = query.where(DriftResult.is_drifted == is_drifted)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        query = query.order_by(JobRun.started_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        rows = result.all()

        enriched_results = []
        for drift_result, field_name, field_threshold, data_type, started_at in rows:
            threshold = self._resolve_threshold(drift_result.metric_name, field_threshold, data_type.value)
            enriched = self._build_enriched_result(drift_result, field_name, threshold, started_at)
            enriched_results.append(
                DriftResultEnriched(
                    id=enriched["id"],
                    job_run_id=enriched["job_run_id"],
                    schema_field_id=enriched["schema_field_id"],
                    field_name=enriched["field_name"],
                    metric_name=enriched["metric_name"],
                    score=enriched["score"],
                    threshold=enriched["threshold"],
                    is_drifted=enriched["is_drifted"],
                    details=enriched["details"],
                    created_at=enriched["created_at"],
                )
            )

        return enriched_results, total

    async def get_drift_overview(
        self, page: int = 1, page_size: int = 10, model_ids: list[uuid.UUID] | None = None
    ) -> tuple[list[dict], int]:
        """Build a per-model drift health summary for all models with active versions."""

        # Count total models with active versions
        count_q = (
            select(func.count(func.distinct(Model.id)))
            .join(ModelVersion, Model.id == ModelVersion.model_id)
            .where(ModelVersion.is_active == True)  # noqa: E712
        )
        if model_ids is not None:
            count_q = count_q.where(Model.id.in_(model_ids))
        total = (await self.db.execute(count_q)).scalar_one()

        # Get models with active versions, paginated
        models_q = (
            select(Model)
            .join(ModelVersion, Model.id == ModelVersion.model_id)
            .where(ModelVersion.is_active == True)  # noqa: E712
            .options(selectinload(Model.versions).selectinload(ModelVersion.schema_fields))
            .order_by(Model.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        if model_ids is not None:
            models_q = models_q.where(Model.id.in_(model_ids))
        result = await self.db.execute(models_q)
        models = result.scalars().unique().all()

        items = []
        for model in models:
            active_version = next((v for v in model.versions if v.is_active), None)
            if not active_version:
                continue

            # Count inferences
            inf_count = (
                await self.db.execute(select(func.count()).where(InferenceData.model_version_id == active_version.id))
            ).scalar_one()

            # Get the latest job run for this version
            latest_run_q = (
                select(JobRun)
                .join(JobConfig, JobRun.job_config_id == JobConfig.id)
                .where(JobConfig.model_version_id == active_version.id)
                .order_by(JobRun.started_at.desc())
                .limit(1)
            )
            latest_run_result = await self.db.execute(latest_run_q)
            latest_run = latest_run_result.scalar_one_or_none()

            # Get drift results from the latest run
            drift_results_enriched = []
            drifted_count = 0
            total_fields = len(active_version.schema_fields)
            last_check = None

            if latest_run:
                last_check = latest_run.started_at
                dr_q = (
                    select(DriftResult, SchemaField.field_name, SchemaField.alert_threshold, SchemaField.data_type)
                    .join(SchemaField, DriftResult.schema_field_id == SchemaField.id)
                    .where(DriftResult.job_run_id == latest_run.id)
                )
                dr_result = await self.db.execute(dr_q)

                for drift_result, field_name, field_threshold, data_type in dr_result.all():
                    threshold = self._resolve_threshold(drift_result.metric_name, field_threshold, data_type.value)
                    drift_results_enriched.append(
                        self._build_enriched_result(drift_result, field_name, threshold, latest_run.started_at)
                    )
                    if drift_result.is_drifted:
                        drifted_count += 1

            # Also get historical results (last 30) for timeline chart
            history_q = (
                select(
                    DriftResult,
                    SchemaField.field_name,
                    SchemaField.alert_threshold,
                    SchemaField.data_type,
                    JobRun.started_at,
                )
                .join(JobRun, DriftResult.job_run_id == JobRun.id)
                .join(JobConfig, JobRun.job_config_id == JobConfig.id)
                .join(SchemaField, DriftResult.schema_field_id == SchemaField.id)
                .where(JobConfig.model_version_id == active_version.id)
                .order_by(JobRun.started_at.desc())
                .limit(2000)  # Allow enough results for 8+ weeks with many fields
            )
            history_result = await self.db.execute(history_q)
            timeline_results = []
            for drift_result, field_name, field_threshold, data_type, started_at in history_result.all():
                threshold = self._resolve_threshold(drift_result.metric_name, field_threshold, data_type.value)
                timeline_results.append(self._build_enriched_result(drift_result, field_name, threshold, started_at))

            health_pct = 100 if total_fields == 0 else round(((total_fields - drifted_count) / total_fields) * 100)

            items.append(
                {
                    "model_id": model.id,
                    "model_name": model.name,
                    "model_description": model.description,
                    "version_id": active_version.id,
                    "version": active_version.version,
                    "total_inferences": inf_count,
                    "total_fields": total_fields,
                    "drifted_fields": drifted_count,
                    "health_percentage": health_pct,
                    "last_check": last_check,
                    "results": timeline_results,
                }
            )

        return items, total

    async def list_notifications(
        self,
        is_read: bool | None = None,
        model_version_id: uuid.UUID | None = None,
        page: int = 1,
        page_size: int = 20,
        model_ids: list[uuid.UUID] | None = None,
    ):
        """List notifications with optional read-status and model-version filters."""
        query = select(Notification)
        if is_read is not None:
            query = query.where(Notification.is_read == is_read)
        if model_version_id is not None:
            query = query.where(Notification.model_version_id == model_version_id)
        if model_ids is not None:
            query = query.join(ModelVersion, Notification.model_version_id == ModelVersion.id).where(
                ModelVersion.model_id.in_(model_ids)
            )

        query = query.order_by(Notification.created_at.desc())
        return await paginate_query(self.db, query, page, page_size)

    async def mark_notification_read(self, notification_id: uuid.UUID) -> Notification:
        """Mark a single notification as read."""
        result = await self.db.execute(select(Notification).where(Notification.id == notification_id))
        notification = result.scalar_one_or_none()
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
        notification.is_read = True
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def mark_all_notifications_read(self, *, model_ids: list[uuid.UUID] | None = None) -> int:
        """Mark all unread notifications as read. Returns the count updated."""
        stmt = select(Notification).where(Notification.is_read == False)  # noqa: E712
        if model_ids is not None:
            stmt = (
                stmt.join(DriftResult, Notification.drift_result_id == DriftResult.id)
                .join(JobRun, DriftResult.job_run_id == JobRun.id)
                .join(JobConfig, JobRun.job_config_id == JobConfig.id)
                .join(ModelVersion, JobConfig.model_version_id == ModelVersion.id)
                .where(ModelVersion.model_id.in_(model_ids))
            )
        result = await self.db.execute(stmt)
        notifications = result.scalars().all()
        for n in notifications:
            n.is_read = True
        await self.db.commit()
        return len(notifications)
