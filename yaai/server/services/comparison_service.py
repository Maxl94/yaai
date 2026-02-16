from __future__ import annotations

import uuid
from datetime import datetime

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.drift.registry import get_metric
from yaai.server.models.model import SchemaField
from yaai.server.schemas.dashboard import (
    CategoricalData,
    CategoricalStatistics,
    HistogramData,
    NumericalStatistics,
)
from yaai.server.services.base import BaseService


class ComparisonPanel:
    """Side-by-side distribution data for a single schema field."""

    def __init__(
        self,
        field_name: str,
        direction: str,
        data_type: str,
        chart_type: str,
        data_a: HistogramData | CategoricalData,
        data_b: HistogramData | CategoricalData,
        drift_score: dict | None = None,
    ):
        self.field_name = field_name
        self.direction = direction
        self.data_type = data_type
        self.chart_type = chart_type
        self.data_a = data_a
        self.data_b = data_b
        self.drift_score = drift_score

    def to_dict(self) -> dict:
        result = {
            "field_name": self.field_name,
            "direction": self.direction,
            "data_type": self.data_type,
            "chart_type": self.chart_type,
            "data_a": self.data_a.model_dump(),
            "data_b": self.data_b.model_dump(),
        }
        if self.drift_score:
            result["drift_score"] = self.drift_score
        return result


class ComparisonService(BaseService):
    """Compares inference distributions across time windows or against reference data."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    @staticmethod
    def _compute_drift_score(field: SchemaField, values_a: list, values_b: list) -> dict | None:
        """Compute drift score between two value sets for a field."""
        if not values_a or not values_b:
            return None
        metric = get_metric(field.drift_metric, field.data_type.value)
        threshold = field.alert_threshold
        output = metric.compute(values_b, values_a, threshold)  # b = reference, a = current
        return {
            "metric_name": output.metric_name,
            "metric_value": output.metric_value,
            "is_drifted": output.is_drifted,
            "threshold": threshold or metric.default_threshold,
        }

    async def compare_time_windows(
        self,
        model_version_id: uuid.UUID,
        from_a: datetime,
        to_a: datetime,
        from_b: datetime,
        to_b: datetime,
    ) -> list[dict]:
        """Compare distributions between two arbitrary time windows."""
        version = await self.get_version_with_schema(model_version_id)
        inferences_a = await self.load_inferences(model_version_id, from_a, to_a)
        inferences_b = await self.load_inferences(model_version_id, from_b, to_b)

        return self._build_comparison_panels(version.schema_fields, inferences_a, inferences_b)

    async def compare_vs_reference(
        self,
        model_version_id: uuid.UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[dict]:
        """Compare a time window's distributions against stored reference data."""
        version = await self.get_version_with_schema(model_version_id)
        inferences = await self.load_inferences(model_version_id, from_ts, to_ts)
        reference = await self.load_reference_data(model_version_id)

        return self._build_comparison_panels(version.schema_fields, inferences, reference)

    def _build_comparison_panels(
        self,
        fields: list[SchemaField],
        data_a: list,
        data_b: list,
    ) -> list[dict]:
        sorted_fields = self.sort_schema_fields(fields)

        panels = []
        for field in sorted_fields:
            values_a = self.extract_field_values(data_a, field)
            values_b = self.extract_field_values(data_b, field)

            if field.data_type.value == "numerical":
                panel = self._build_numerical_comparison(field, values_a, values_b)
            else:
                panel = self._build_categorical_comparison(field, values_a, values_b)
            panels.append(panel.to_dict())

        return panels

    def _build_numerical_comparison(
        self,
        field: SchemaField,
        values_a: list,
        values_b: list,
    ) -> ComparisonPanel:
        num_a = [v for v in values_a if v is not None]
        num_b = [v for v in values_b if v is not None]

        # Compute shared bucket boundaries from the union range
        all_values = num_a + num_b
        num_buckets = 20

        if not all_values:
            empty = HistogramData(
                buckets=[],
                statistics=NumericalStatistics(mean=0, median=0, std=0, min=0, max=0, count=0, null_count=0),
            )
            return ComparisonPanel(
                field_name=field.field_name,
                direction=field.direction.value,
                data_type="numerical",
                chart_type="histogram",
                data_a=empty,
                data_b=empty,
            )

        combined = np.array(all_values, dtype=float)
        min_val, max_val = float(combined.min()), float(combined.max())

        if min_val == max_val:
            edges = np.array([min_val, max_val + 1])
        else:
            edges = np.linspace(min_val, max_val, num_buckets + 1)

        data_a_hist = self._histogram_from_edges(num_a, edges, len(values_a) - len(num_a))
        data_b_hist = self._histogram_from_edges(num_b, edges, len(values_b) - len(num_b))

        return ComparisonPanel(
            field_name=field.field_name,
            direction=field.direction.value,
            data_type="numerical",
            chart_type="histogram",
            data_a=data_a_hist,
            data_b=data_b_hist,
            drift_score=self._compute_drift_score(field, num_a, num_b),
        )

    def _build_categorical_comparison(
        self,
        field: SchemaField,
        values_a: list,
        values_b: list,
    ) -> ComparisonPanel:
        non_null_a = [v for v in values_a if v is not None]
        non_null_b = [v for v in values_b if v is not None]

        data_a_cat = self._categorical_data(non_null_a, len(values_a) - len(non_null_a))
        data_b_cat = self._categorical_data(non_null_b, len(values_b) - len(non_null_b))

        return ComparisonPanel(
            field_name=field.field_name,
            direction=field.direction.value,
            data_type="categorical",
            chart_type="bar",
            data_a=data_a_cat,
            data_b=data_b_cat,
            drift_score=self._compute_drift_score(field, non_null_a, non_null_b),
        )

    @staticmethod
    def _histogram_from_edges(values: list, edges: np.ndarray, null_count: int) -> HistogramData:
        if not values:
            return HistogramData(
                buckets=[],
                statistics=NumericalStatistics(mean=0, median=0, std=0, min=0, max=0, count=0, null_count=null_count),
            )

        arr = np.array(values, dtype=float)
        counts = np.histogram(arr, bins=edges)[0]
        buckets = BaseService.build_histogram_buckets(edges, counts)
        return HistogramData(
            buckets=buckets,
            statistics=BaseService.compute_numerical_statistics(arr, values, null_count),
        )

    @staticmethod
    def _categorical_data(values: list, null_count: int) -> CategoricalData:
        categories, stats = BaseService.build_category_counts(values)
        # Override null_count from the passed parameter
        stats = CategoricalStatistics(
            unique_count=stats.unique_count,
            total_count=stats.total_count,
            null_count=null_count,
            top_category=stats.top_category,
        )
        return CategoricalData(categories=categories, statistics=stats)
