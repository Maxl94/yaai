from __future__ import annotations

import uuid
from datetime import datetime

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.schemas.model import FieldDirection
from yaai.server.config import settings
from yaai.server.models.inference import InferenceData
from yaai.server.models.model import SchemaField
from yaai.server.schemas.dashboard import (
    CategoricalData,
    CategoricalStatistics,
    CategoryCount,
    DashboardPanel,
    HistogramData,
    LatestDrift,
    NumericalStatistics,
    SampleInfo,
)
from yaai.server.services.base import BaseService
from yaai.server.services.histogram import (
    LOWER_PERCENTILE,
    TAIL_FACTOR,
    UPPER_PERCENTILE,
    BinSpec,
    buckets_from_counts,
    build_histogram,
)

_NUM_BUCKETS = 20


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
        latest_drift = await self._get_latest_drift_per_field(model_version_id)
        sorted_fields = self.sort_schema_fields(version.schema_fields)

        # Detect dialect once.  PostgreSQL supports server-side aggregation
        # (width_bucket, percentile_cont, json_extract_path_text).  Other
        # dialects (e.g. SQLite used in tests) fall back to Python-side computation.
        conn = await self.db.connection()
        is_pg = conn.dialect.name == "postgresql"

        panels = []

        if is_pg:
            max_s = settings.dashboard_max_samples

            # Exact total record count – one cheap index scan, no JSON read.
            exact_total = await self._fetch_exact_total(model_version_id, from_ts, to_ts)

            for field in sorted_fields:
                drift_info = latest_drift.get(field.id)
                if field.data_type.value == "numerical":
                    panel = await self._build_numerical_panel_sql(
                        model_version_id,
                        field,
                        from_ts,
                        to_ts,
                        drift_info,
                        exact_total=exact_total,
                        max_samples=max_s,
                    )
                else:
                    panel = await self._build_categorical_panel_sql(
                        model_version_id,
                        field,
                        from_ts,
                        to_ts,
                        drift_info,
                        exact_total=exact_total,
                        max_samples=max_s,
                    )
                panels.append(panel)
        else:
            # Fallback: load all records once and compute in Python.
            inferences = await self._load_inferences_optional(model_version_id, from_ts, to_ts)
            for field in sorted_fields:
                drift_info = latest_drift.get(field.id)
                values = self.extract_field_values(inferences, field)
                if field.data_type.value == "numerical":
                    panel = self._build_numerical_panel(field, values, drift_info)
                else:
                    panel = self._build_categorical_panel(field, values, drift_info)
                panels.append(panel)

        return panels

    # ------------------------------------------------------------------
    # Shared pre-computation helpers
    # ------------------------------------------------------------------

    def _build_time_where(
        self,
        model_version_id: uuid.UUID,
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> tuple[str, dict]:
        """Build a parameterised WHERE clause for inference_data queries."""
        clauses = ["model_version_id = :version_id"]
        params: dict = {"version_id": model_version_id}
        if from_ts:
            clauses.append("timestamp >= :from_ts")
            params["from_ts"] = from_ts
        if to_ts:
            clauses.append("timestamp <= :to_ts")
            params["to_ts"] = to_ts
        return " AND ".join(clauses), params

    async def _fetch_exact_total(
        self,
        model_version_id: uuid.UUID,
        from_ts: datetime | None,
        to_ts: datetime | None,
    ) -> int:
        """Count all inference records in the time window – uses index, no JSON read."""
        where, params = self._build_time_where(model_version_id, from_ts, to_ts)
        row = (
            await self.db.execute(text(f"SELECT count(*) AS n FROM inference_data WHERE {where}"), params)
        ).fetchone()
        return int(row.n)

    # ------------------------------------------------------------------
    # PostgreSQL panel builders
    # ------------------------------------------------------------------

    async def _build_numerical_panel_sql(
        self,
        model_version_id: uuid.UUID,
        field: SchemaField,
        from_ts: datetime | None,
        to_ts: datetime | None,
        drift_info: LatestDrift | None,
        *,
        exact_total: int,
        max_samples: int,
    ) -> DashboardPanel:
        """Build a numerical histogram panel using the most-recent N rows as sample.

        All statistics (mean, std, median, min, max, histogram) come from the sample.
        ``exact_total`` is the full record count from a cheap index-only COUNT(*) and
        is surfaced in ``sample_info`` so the UI can show an info indicator.

        Histogram bins are equal-width and empty bins are included. Long tails beyond p1 / p99 are
        collected in underflow / overflow buckets (see ``services.histogram``).

        Note: min/max reflect the sample window (most recent N records), not the
        all-time extremes.  This is intentional — for monitoring, current distribution
        bounds are more meaningful than historical outliers.  Getting exact all-time
        min/max would require a full JSON-column scan (~same cost as the original
        unsampled query), which would negate the sampling performance gain.
        """
        col = "inputs" if field.direction == FieldDirection.INPUT else "outputs"
        where, params = self._build_time_where(model_version_id, from_ts, to_ts)
        params["field_name"] = field.field_name
        params["num_buckets"] = _NUM_BUCKETS
        params["overflow_bucket"] = _NUM_BUCKETS + 1
        params["lower_q"] = LOWER_PERCENTILE / 100
        params["upper_q"] = UPPER_PERCENTILE / 100
        params["tail_factor"] = TAIL_FACTOR
        params["max_samples"] = max_samples

        sql = text(
            f"""
            WITH sampled AS (
                SELECT {col}
                FROM inference_data
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT :max_samples
            ),
            parsed AS (
                SELECT CAST(json_extract_path_text({col}, :field_name) AS DOUBLE PRECISION) AS raw_val
                FROM sampled
            ),
            data AS (
                -- NaN / +-Infinity (accepted by the cast from JSON strings) count as NULL, like in the Python path
                SELECT CASE
                    WHEN raw_val IN (
                        CAST('NaN' AS DOUBLE PRECISION),
                        CAST('Infinity' AS DOUBLE PRECISION),
                        CAST('-Infinity' AS DOUBLE PRECISION)
                    ) THEN NULL
                    ELSE raw_val
                END AS val
                FROM parsed
            ),
            agg AS (
                SELECT
                    avg(val)                                          AS mean,
                    stddev_pop(val)                                   AS std,
                    min(val)                                          AS sample_min,
                    max(val)                                          AS sample_max,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY val) AS median,
                    percentile_cont(ARRAY[CAST(:lower_q AS double precision), CAST(:upper_q AS double precision)])
                        WITHIN GROUP (ORDER BY val) AS pcts,
                    count(val)                                        AS sample_non_null,
                    count(*)                                          AS sample_total
                FROM data
            ),
            bounds AS (
                SELECT
                    agg.*,
                    CASE WHEN pcts[1] < pcts[2] AND pcts[1] - sample_min > :tail_factor * (pcts[2] - pcts[1])
                         THEN pcts[1] ELSE sample_min END AS lo,
                    CASE WHEN pcts[1] < pcts[2] AND sample_max - pcts[2] > :tail_factor * (pcts[2] - pcts[1])
                         THEN pcts[2] ELSE sample_max END AS hi
                FROM agg
            ),
            hist AS (
                SELECT
                    CASE
                        WHEN d.val < b.lo THEN 0
                        WHEN d.val > b.hi THEN CAST(:overflow_bucket AS integer)
                        ELSE LEAST(width_bucket(d.val, b.lo, b.hi, :num_buckets), :num_buckets)
                    END AS bucket,
                    count(*) AS cnt
                FROM data d
                CROSS JOIN bounds b
                WHERE d.val IS NOT NULL
                  AND b.lo IS NOT NULL
                  AND b.lo < b.hi
                GROUP BY 1
            )
            SELECT
                b.mean, b.std, b.sample_min, b.sample_max, b.median, b.lo, b.hi,
                b.sample_non_null, b.sample_total,
                s.bucket, coalesce(h.cnt, 0) AS cnt
            FROM bounds b
            CROSS JOIN generate_series(0, CAST(:overflow_bucket AS integer)) AS s(bucket)
            LEFT JOIN hist h ON h.bucket = s.bucket
            ORDER BY s.bucket
        """
        )

        rows = (await self.db.execute(sql, params)).fetchall()

        r0 = rows[0]
        sample_total = int(r0.sample_total)
        sample_non_null = int(r0.sample_non_null or 0)
        null_count = sample_total - sample_non_null

        sample_info = SampleInfo(
            sample_size=sample_total,
            total_count=exact_total,
            is_sampled=exact_total > sample_total,
        )

        if sample_non_null == 0:
            stats = NumericalStatistics(mean=0, median=0, std=0, min=0, max=0, count=0, null_count=null_count)
            return DashboardPanel(
                field_name=field.field_name,
                direction=field.direction.value,
                data_type=field.data_type.value,
                chart_type="histogram",
                data=HistogramData(buckets=[], statistics=stats),
                latest_drift=drift_info,
                sample_info=sample_info,
            )

        min_v = float(r0.sample_min)
        max_v = float(r0.sample_max)

        stats = NumericalStatistics(
            mean=round(float(r0.mean), 4),
            median=round(float(r0.median), 4),
            std=round(float(r0.std or 0), 4),
            min=round(min_v, 4),
            max=round(max_v, 4),
            count=sample_non_null,
            null_count=null_count,
        )

        spec = BinSpec.create(float(r0.lo), float(r0.hi), _NUM_BUCKETS, min_v, max_v)
        if spec.num_bins == 1:
            counts = (0, [sample_non_null], 0)
        else:
            by_bucket = {int(r.bucket): int(r.cnt) for r in rows}
            counts = (
                by_bucket[0],
                [by_bucket[i] for i in range(1, _NUM_BUCKETS + 1)],
                by_bucket[_NUM_BUCKETS + 1],
            )
        buckets = buckets_from_counts(spec, *counts)

        return DashboardPanel(
            field_name=field.field_name,
            direction=field.direction.value,
            data_type=field.data_type.value,
            chart_type="histogram",
            data=HistogramData(buckets=buckets, statistics=stats),
            latest_drift=drift_info,
            sample_info=sample_info,
        )

    async def _build_categorical_panel_sql(
        self,
        model_version_id: uuid.UUID,
        field: SchemaField,
        from_ts: datetime | None,
        to_ts: datetime | None,
        drift_info: LatestDrift | None,
        *,
        exact_total: int,
        max_samples: int,
    ) -> DashboardPanel:
        """Build a categorical bar-chart panel from the most-recent N rows.

        Category percentages are sample-based (representative).
        ``total_count`` in ``CategoricalStatistics`` reflects the full population.
        """
        col = "inputs" if field.direction == FieldDirection.INPUT else "outputs"
        where, params = self._build_time_where(model_version_id, from_ts, to_ts)
        params["field_name"] = field.field_name
        params["max_samples"] = max_samples

        sql = text(
            f"""
            WITH sampled AS (
                SELECT {col}
                FROM inference_data
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT :max_samples
            ),
            counts AS (
                SELECT
                    json_extract_path_text({col}, :field_name) AS category,
                    count(*) AS cnt
                FROM sampled
                GROUP BY category
            )
            SELECT category, cnt, sum(cnt) OVER () AS sample_total
            FROM counts
            ORDER BY cnt DESC
        """
        )

        rows = (await self.db.execute(sql, params)).fetchall()

        sample_total = int(rows[0].sample_total) if rows else 0
        sample_info = SampleInfo(
            sample_size=sample_total,
            total_count=exact_total,
            is_sampled=exact_total > sample_total,
        )

        if not rows:
            cat_stats = CategoricalStatistics(unique_count=0, total_count=0, null_count=0, top_category=None)
            return DashboardPanel(
                field_name=field.field_name,
                direction=field.direction.value,
                data_type=field.data_type.value,
                chart_type="bar",
                data=CategoricalData(categories=[], statistics=cat_stats),
                latest_drift=drift_info,
                sample_info=sample_info,
            )

        sample_null_cnt = sum(int(r.cnt) for r in rows if r.category is None)
        sample_non_null = sample_total - sample_null_cnt
        non_null_rows = [r for r in rows if r.category is not None]

        categories = [
            CategoryCount(
                value=r.category,
                count=int(r.cnt),
                percentage=round(int(r.cnt) / sample_non_null * 100, 2) if sample_non_null > 0 else 0.0,
            )
            for r in non_null_rows
        ]
        cat_stats = CategoricalStatistics(
            unique_count=len(non_null_rows),
            total_count=sample_non_null,
            null_count=sample_null_cnt,
            top_category=non_null_rows[0].category if non_null_rows else None,
        )

        return DashboardPanel(
            field_name=field.field_name,
            direction=field.direction.value,
            data_type=field.data_type.value,
            chart_type="bar",
            data=CategoricalData(categories=categories, statistics=cat_stats),
            latest_drift=drift_info,
            sample_info=sample_info,
        )

    # ------------------------------------------------------------------
    # SQLite fallback panel builders (used in tests)
    # ------------------------------------------------------------------

    def _build_numerical_panel(
        self,
        field: SchemaField,
        values: list,
        drift_info: LatestDrift | None,
    ) -> DashboardPanel:
        numeric_values = [v for v in values if v is not None]
        null_count = len(values) - len(numeric_values)

        if not numeric_values:
            stats = NumericalStatistics(mean=0, median=0, std=0, min=0, max=0, count=0, null_count=null_count)
            return DashboardPanel(
                field_name=field.field_name,
                direction=field.direction.value,
                data_type=field.data_type.value,
                chart_type="histogram",
                data=HistogramData(buckets=[], statistics=stats),
                latest_drift=drift_info,
            )

        arr = np.array(numeric_values, dtype=float)
        buckets = build_histogram(arr, _NUM_BUCKETS)

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
        non_null = [v for v in values if v is not None]
        null_count = len(values) - len(non_null)

        categories, stats = self.build_category_counts(non_null)
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
        """Get the most recent drift result per schema field.

        Uses DISTINCT ON on PostgreSQL (efficient).  Falls back to a correlated
        MAX subquery on other dialects (e.g. SQLite in tests).
        """
        conn = await self.db.connection()
        if conn.dialect.name == "postgresql":
            sql = text("""
                SELECT DISTINCT ON (dr.schema_field_id)
                    dr.schema_field_id,
                    dr.metric_name,
                    dr.metric_value,
                    dr.is_drifted,
                    jr.started_at
                FROM drift_results dr
                JOIN job_runs jr ON dr.job_run_id = jr.id
                JOIN job_configs jc ON jr.job_config_id = jc.id
                WHERE jc.model_version_id = :version_id
                ORDER BY dr.schema_field_id, jr.started_at DESC
            """)
            rows = (await self.db.execute(sql, {"version_id": model_version_id})).fetchall()
            return {
                row.schema_field_id: LatestDrift(
                    metric_name=row.metric_name,
                    metric_value=row.metric_value,
                    is_drifted=row.is_drifted,
                    calculated_at=row.started_at,
                )
                for row in rows
            }

        # Non-PostgreSQL fallback (e.g. SQLite in tests): use ORM + Python dedup.
        # Avoids DISTINCT ON and UUID binding issues present in raw-SQL dialects.
        from yaai.server.models.job import DriftResult, JobConfig, JobRun  # noqa: PLC0415

        stmt = (
            select(DriftResult, JobRun.started_at)
            .join(JobRun, DriftResult.job_run_id == JobRun.id)
            .join(JobConfig, JobRun.job_config_id == JobConfig.id)
            .where(JobConfig.model_version_id == model_version_id)
            .order_by(JobRun.started_at.desc())
        )
        result = await self.db.execute(stmt)
        latest: dict[uuid.UUID, LatestDrift] = {}
        for dr, started_at in result.all():
            if dr.schema_field_id not in latest:
                latest[dr.schema_field_id] = LatestDrift(
                    metric_name=dr.metric_name,
                    metric_value=dr.metric_value,
                    is_drifted=dr.is_drifted,
                    calculated_at=started_at,
                )
        return latest
