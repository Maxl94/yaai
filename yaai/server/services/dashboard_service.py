from __future__ import annotations

import uuid
from datetime import datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.models.inference import InferenceData
from yaai.server.models.job import DriftResult, JobConfig, JobRun
from yaai.server.models.model import SchemaField
from yaai.server.schemas.dashboard import (
    CategoricalData,
    CategoricalStatistics,
    DashboardPanel,
    HistogramBucket,
    HistogramData,
    LatestDrift,
    NumericalStatistics,
)
from yaai.server.services.base import BaseService


class DashboardService(BaseService):
    """Builds per-field dashboard panels with distribution data and drift status."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def get_dashboard(
        self,
        model_version_id: uuid.UUID,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> list[DashboardPanel]:
        """Return dashboard panels for all schema fields of a model version."""
        version = await self.get_version_with_schema(model_version_id)
        inferences = await self._load_inferences_optional(model_version_id, from_ts, to_ts)
        latest_drift = await self._get_latest_drift_per_field(model_version_id)

        sorted_fields = self.sort_schema_fields(version.schema_fields)

        panels = []
        for field in sorted_fields:
            values = self.extract_field_values(inferences, field)
            drift_info = latest_drift.get(field.id)

            if field.data_type.value == "numerical":
                panel = self._build_numerical_panel(field, values, drift_info)
            else:
                panel = self._build_categorical_panel(field, values, drift_info)
            panels.append(panel)

        return panels

    def _build_numerical_panel(
        self,
        field: SchemaField,
        values: list,
        drift_info: LatestDrift | None,
    ) -> DashboardPanel:
        """Build a histogram panel with summary statistics for a numerical field."""
        numeric_values = [v for v in values if v is not None]
        null_count = len(values) - len(numeric_values)

        if not numeric_values:
            stats = NumericalStatistics(
                mean=0,
                median=0,
                std=0,
                min=0,
                max=0,
                count=0,
                null_count=null_count,
            )
            return DashboardPanel(
                field_name=field.field_name,
                direction=field.direction.value,
                data_type=field.data_type.value,
                chart_type="histogram",
                data=HistogramData(buckets=[], statistics=stats),
                latest_drift=drift_info,
            )

        arr = np.array(numeric_values, dtype=float)
        num_buckets = min(20, len(numeric_values))
        min_val, max_val = float(arr.min()), float(arr.max())

        if min_val == max_val:
            buckets = [HistogramBucket(range_start=min_val, range_end=max_val, count=len(numeric_values))]
        else:
            edges = np.linspace(min_val, max_val, num_buckets + 1)
            counts = np.histogram(arr, bins=edges)[0]
            buckets = self.build_histogram_buckets(edges, counts)

        stats = self.compute_numerical_statistics(arr, numeric_values, null_count)

        return DashboardPanel(
            field_name=field.field_name,
            direction=field.direction.value,
            data_type=field.data_type.value,
            chart_type="histogram",
            data=HistogramData(buckets=buckets, statistics=stats),
            latest_drift=drift_info,
        )

    def _build_categorical_panel(
        self,
        field: SchemaField,
        values: list,
        drift_info: LatestDrift | None,
    ) -> DashboardPanel:
        """Build a bar-chart panel with category counts for a categorical field."""
        non_null = [v for v in values if v is not None]
        null_count = len(values) - len(non_null)

        categories, stats = self.build_category_counts(non_null)
        # Override null_count from the passed parameter
        stats = CategoricalStatistics(
            unique_count=stats.unique_count,
            total_count=stats.total_count,
            null_count=null_count,
            top_category=stats.top_category,
        )

        return DashboardPanel(
            field_name=field.field_name,
            direction=field.direction.value,
            data_type=field.data_type.value,
            chart_type="bar",
            data=CategoricalData(categories=categories, statistics=stats),
            latest_drift=drift_info,
        )

    async def _load_inferences_optional(
        self,
        model_version_id: uuid.UUID,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> list[InferenceData]:
        """Load inferences with optional time range filtering."""
        query = select(InferenceData).where(InferenceData.model_version_id == model_version_id)
        if from_ts:
            query = query.where(InferenceData.timestamp >= from_ts)
        if to_ts:
            query = query.where(InferenceData.timestamp <= to_ts)
        query = query.order_by(InferenceData.timestamp)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _get_latest_drift_per_field(
        self,
        model_version_id: uuid.UUID,
    ) -> dict[uuid.UUID, LatestDrift]:
        """Get the most recent drift result per schema field."""
        result = await self.db.execute(
            select(DriftResult, JobRun.started_at)
            .join(JobRun)
            .join(JobConfig)
            .where(JobConfig.model_version_id == model_version_id)
            .order_by(JobRun.started_at.desc())
        )
        rows = result.all()

        latest: dict[uuid.UUID, LatestDrift] = {}
        for drift_result, started_at in rows:
            if drift_result.schema_field_id not in latest:
                latest[drift_result.schema_field_id] = LatestDrift(
                    metric_name=drift_result.metric_name,
                    metric_value=drift_result.metric_value,
                    is_drifted=drift_result.is_drifted,
                    calculated_at=started_at,
                )
        return latest
