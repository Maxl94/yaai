from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func as sql_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.schemas.model import FieldDirection
from yaai.server.drift.registry import get_metric
from yaai.server.models.inference import InferenceData
from yaai.server.models.job import (
    ComparisonType,
    DriftResult,
    JobConfig,
    JobRun,
    JobStatus,
    Notification,
    NotificationSeverity,
)
from yaai.server.models.model import ModelVersion, SchemaField
from yaai.server.services.base import BaseService

logger = logging.getLogger(__name__)

# Threshold for distinguishing bounded metrics (chi_squared, ks_test) from distance metrics (PSI, JS)
BOUNDED_METRIC_THRESHOLD = 0.5


# Mapping of time unit patterns to timedelta factory functions
_WINDOW_UNITS = {
    "h": lambda v: timedelta(hours=v),
    "hour": lambda v: timedelta(hours=v),
    "d": lambda v: timedelta(days=v),
    "day": lambda v: timedelta(days=v),
    "w": lambda v: timedelta(weeks=v),
    "week": lambda v: timedelta(weeks=v),
}


def parse_window_size(window_size: str) -> timedelta:
    """Parse a human-readable window size like '1 day', '7 days', '7d', '24h' into a timedelta."""
    match = re.match(r"(\d+)\s*(h|hour|d|day|w|week)s?", window_size.strip().lower())
    if not match:
        msg = f"Invalid window_size format: {window_size}"
        raise ValueError(msg)

    amount = int(match.group(1))
    unit = match.group(2)
    return _WINDOW_UNITS[unit](amount)


class DriftService(BaseService):
    """Service for detecting data drift between reference and inference datasets.

    Provides methods to run drift detection jobs, trigger manual runs, and
    backfill historical drift results across configurable time windows.

    Attributes:
        MAX_WINDOW: Maximum allowed window size for auto-extension (90 days).
        db: Async database session used for all queries and persistence.
    """

    MAX_WINDOW = timedelta(days=90)

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def _load_inferences_auto_extend(
        self,
        model_version_id: uuid.UUID,
        to_ts: datetime,
        configured_window: timedelta,
        min_samples: int,
    ) -> tuple[list[InferenceData], timedelta]:
        """Load inferences, auto-extending the window backward until min_samples is met."""
        actual_window = configured_window
        inference_data = await self.load_inferences(model_version_id, to_ts - actual_window, to_ts)

        while len(inference_data) < min_samples and actual_window < self.MAX_WINDOW:
            actual_window = min(actual_window * 2, self.MAX_WINDOW)
            inference_data = await self.load_inferences(model_version_id, to_ts - actual_window, to_ts)

        return inference_data, actual_window

    def _build_window_info(
        self,
        configured_window: timedelta,
        actual_window: timedelta,
        min_samples: int,
        sample_count: int,
    ) -> dict:
        return {
            "configured_window_days": configured_window.total_seconds() / 86400,
            "actual_window_days": actual_window.total_seconds() / 86400,
            "window_extended": actual_window > configured_window,
            "min_samples": min_samples,
            "sample_count": sample_count,
        }

    async def _load_datasets_for_comparison(
        self,
        job_config: JobConfig,
        period_end: datetime,
        window: timedelta,
        min_samples: int,
    ) -> tuple[list, list[InferenceData], timedelta]:
        """Load reference and inference datasets based on comparison type.

        Returns:
            A tuple of (reference_data, inference_data, actual_window).

        Raises:
            ValueError: If no reference or inference data is available.
        """
        if job_config.comparison_type == ComparisonType.VS_REFERENCE:
            reference_data = await self.load_reference_data(job_config.model_version_id)
            if not reference_data:
                msg = "No reference data available for this model version"
                raise ValueError(msg)
            inference_data, actual_window = await self._load_inferences_auto_extend(
                job_config.model_version_id,
                period_end,
                window,
                min_samples,
            )
        else:  # ROLLING_WINDOW
            inference_data, actual_window = await self._load_inferences_auto_extend(
                job_config.model_version_id,
                period_end,
                window,
                min_samples,
            )
            reference_data = await self._load_inferences_as_dicts(
                job_config.model_version_id,
                period_end - actual_window * 2,
                period_end - actual_window,
            )
            if not reference_data:
                msg = "No data available for the previous time window"
                raise ValueError(msg)

        return reference_data, inference_data, actual_window

    async def _execute_drift_detection(
        self,
        job_config: JobConfig,
        version: ModelVersion,
        period_end: datetime,
        job_run_id: uuid.UUID,
        create_notifications: bool = True,
    ) -> list[DriftResult]:
        """Core drift detection logic used by both run_drift_detection and backfill.

        Args:
            job_config: The job configuration to execute.
            version: The model version with schema fields.
            period_end: The end timestamp for the detection period.
            job_run_id: Primary key of the owning JobRun.
            create_notifications: Whether to create notifications for drifted fields.

        Returns:
            A list of DriftResult objects (one per schema field).

        Raises:
            ValueError: If no inference data is available for the period.
        """
        window = parse_window_size(job_config.window_size or "7 days")
        min_samples = job_config.min_samples or 200

        reference_data, inference_data, actual_window = await self._load_datasets_for_comparison(
            job_config,
            period_end,
            window,
            min_samples,
        )

        if not inference_data:
            msg = f"No inference data for period ending {period_end}"
            raise ValueError(msg)

        window_info = self._build_window_info(window, actual_window, min_samples, len(inference_data))

        results = []
        for field in version.schema_fields:
            drift_result = self._compute_field_drift(
                field,
                reference_data,
                inference_data,
                job_config,
                job_run_id,
                window_info,
            )
            self.db.add(drift_result)
            results.append(drift_result)

            if create_notifications and drift_result.is_drifted:
                notification = self._create_drift_notification(field, drift_result, version, job_config)
                self.db.add(notification)

        await self.db.flush()
        return results

    async def run_drift_detection(self, job_config_id: uuid.UUID, job_run_id: uuid.UUID) -> list[DriftResult]:
        """Run a full drift detection pass for every schema field in a job.

        Loads the job configuration, resolves reference and inference data based
        on the comparison type (VS_REFERENCE or ROLLING_WINDOW), computes drift
        metrics for each schema field, and persists the results. Notifications
        are created for any field that is flagged as drifted.

        Args:
            job_config_id: Primary key of the ``JobConfig`` to execute.
            job_run_id: Primary key of the parent ``JobRun`` that owns the
                resulting ``DriftResult`` rows.

        Returns:
            A list of ``DriftResult`` objects (one per schema field), already
            added to the database session.

        Raises:
            ValueError: If no reference or inference data is available for the
                configured comparison type and time window.
        """
        job_config = await self._get_job_config(job_config_id)
        version = await self.get_version_with_schema(job_config.model_version_id)
        now = datetime.now(UTC)

        return await self._execute_drift_detection(
            job_config,
            version,
            now,
            job_run_id,
            create_notifications=True,
        )

    async def execute_job(self, job_config_id: uuid.UUID) -> JobRun:
        """Create a job run, execute drift detection, and update the run status.

        Creates a new ``JobRun`` in RUNNING state, delegates to
        ``run_drift_detection``, and marks the run as COMPLETED or FAILED
        depending on the outcome. The transaction is committed before
        returning.

        Args:
            job_config_id: Primary key of the ``JobConfig`` to execute.

        Returns:
            The ``JobRun`` with its final status (COMPLETED or FAILED) and
            timestamps populated.
        """
        job_run = JobRun(
            job_config_id=job_config_id,
            status=JobStatus.RUNNING,
        )
        self.db.add(job_run)
        await self.db.flush()

        try:
            await self.run_drift_detection(job_config_id, job_run.id)
            job_run.status = JobStatus.COMPLETED
            job_run.completed_at = datetime.now(UTC)
        except Exception as e:
            job_run.status = JobStatus.FAILED
            job_run.completed_at = datetime.now(UTC)
            job_run.error_message = str(e)

        await self.db.commit()
        return job_run

    async def trigger_job(self, job_id: uuid.UUID) -> JobRun:
        """Manually trigger a one-off drift detection run for a job.

        Looks up the ``JobConfig`` and delegates to ``execute_job``.

        Args:
            job_id: Primary key of the ``JobConfig`` to trigger.

        Returns:
            The resulting ``JobRun`` with its final status.

        Raises:
            HTTPException: If no ``JobConfig`` with the given id exists (404).
        """
        job_config = await self._get_job_config(job_id)
        return await self.execute_job(job_config.id)

    async def backfill_job(self, job_config_id: uuid.UUID) -> list[JobRun]:
        """Run drift detection for all historical time windows.

        Creates a ``JobRun`` for each past period based on the job's
        ``window_size``, iterating backward from now to the earliest recorded
        inference timestamp. Periods that fail are logged and skipped so that
        subsequent periods can still be processed.

        Args:
            job_config_id: Primary key of the ``JobConfig`` to backfill.

        Returns:
            A list of ``JobRun`` objects created during the backfill, in
            reverse chronological order (most recent period first).
        """
        job_config = await self._get_job_config(job_config_id)
        version = await self.get_version_with_schema(job_config.model_version_id)

        window = parse_window_size(job_config.window_size or "7 days")
        now = datetime.now(UTC)

        # Find the earliest inference data
        earliest_ts = await self._get_earliest_inference_timestamp(job_config.model_version_id)
        if not earliest_ts:
            return []  # No data to backfill

        # Calculate how many periods to backfill
        runs = []
        period_end = now

        while period_end - window >= earliest_ts:
            period_start = period_end - window

            # Run drift detection for this specific period
            try:
                job_run = await self._execute_job_for_period(job_config, version, period_end)
                runs.append(job_run)
            except Exception as e:
                # Log error but continue with other periods
                logger.warning(f"Backfill period {period_start} to {period_end} failed: {e}")

            # Move to the previous period
            period_end = period_start

        await self.db.commit()
        return runs

    async def _execute_job_for_period(
        self,
        job_config: JobConfig,
        version: ModelVersion,
        period_end: datetime,
    ) -> JobRun:
        """Execute drift detection for a specific time period (used for backfill)."""
        job_run = JobRun(
            job_config_id=job_config.id,
            status=JobStatus.RUNNING,
            started_at=period_end,  # Use the period end as the "run time"
        )
        self.db.add(job_run)
        await self.db.flush()

        try:
            await self._run_drift_for_period(job_config, version, period_end, job_run.id)
            job_run.status = JobStatus.COMPLETED
            job_run.completed_at = period_end
        except Exception as e:
            job_run.status = JobStatus.FAILED
            job_run.completed_at = period_end
            job_run.error_message = str(e)

        await self.db.flush()
        return job_run

    async def _run_drift_for_period(
        self,
        job_config: JobConfig,
        version: ModelVersion,
        period_end: datetime,
        job_run_id: uuid.UUID,
    ) -> list[DriftResult]:
        """Run drift detection for a specific time period."""
        return await self._execute_drift_detection(
            job_config,
            version,
            period_end,
            job_run_id,
            create_notifications=False,
        )

    async def _get_earliest_inference_timestamp(self, model_version_id: uuid.UUID) -> datetime | None:
        """Get the timestamp of the earliest inference for a model version."""
        result = await self.db.execute(
            select(sql_func.min(InferenceData.timestamp)).where(InferenceData.model_version_id == model_version_id)
        )
        return result.scalar_one_or_none()

    def _compute_field_drift(
        self,
        field: SchemaField,
        reference_data: list,
        inference_data: list[InferenceData],
        job_config: JobConfig,
        job_run_id: uuid.UUID,
        window_info: dict | None = None,
    ) -> DriftResult:
        """Compute the drift metric for a single schema field.

        Extracts the relevant values from reference and inference data,
        looks up the configured metric, and returns a ``DriftResult``
        populated with the computed statistic and drift flag.

        Args:
            field: The schema field to evaluate.
            reference_data: Reference dataset (``ReferenceData`` models or raw
                dicts when using rolling-window mode).
            inference_data: Current inference records to compare against the
                reference.
            job_config: The parent job configuration.
            job_run_id: Primary key of the owning ``JobRun``.
            window_info: Optional dict of window metadata to embed in the
                result details.

        Returns:
            A ``DriftResult`` instance (not yet flushed to the database).
        """
        ref_values = self._extract_values_from_dicts_or_models(reference_data, field)
        act_values = self._extract_values_from_models(inference_data, field)

        metric = get_metric(field.drift_metric, field.data_type.value)
        threshold = field.alert_threshold
        output = metric.compute(ref_values, act_values, threshold)

        details = output.details or {}
        if window_info:
            details["window"] = window_info

        return DriftResult(
            job_run_id=job_run_id,
            schema_field_id=field.id,
            metric_name=output.metric_name,
            metric_value=output.metric_value,
            is_drifted=output.is_drifted,
            details=details,
        )

    def _create_drift_notification(
        self,
        field: SchemaField,
        drift_result: DriftResult,
        version: ModelVersion,
        job_config: JobConfig,
    ) -> Notification:
        """Create a drift notification for a field that has been flagged as drifted.

        Severity is determined by how far the metric value exceeds the
        configured threshold: WARNING for moderate exceedances, CRITICAL for
        large ones.

        Args:
            field: The schema field that drifted.
            drift_result: The computed ``DriftResult`` containing the metric
                value and drift flag.
            version: The ``ModelVersion`` associated with the field.
            job_config: The parent job configuration.

        Returns:
            A ``Notification`` instance (not yet flushed to the database).
        """
        metric = get_metric(field.drift_metric, field.data_type.value)
        threshold = field.alert_threshold or metric.default_threshold

        # All metrics use higher = more drift; determine severity by how far past threshold
        if threshold >= BOUNDED_METRIC_THRESHOLD:
            # Bounded metrics (chi_squared, ks_test) with threshold near 1.0
            # CRITICAL if past midpoint between threshold and 1.0
            severity = (
                NotificationSeverity.CRITICAL
                if drift_result.metric_value > (1.0 + threshold) / 2
                else NotificationSeverity.WARNING
            )
        else:
            # Distance metrics (PSI, JS) with low thresholds
            # CRITICAL if more than double the threshold
            severity = (
                NotificationSeverity.CRITICAL
                if drift_result.metric_value > threshold * 2
                else NotificationSeverity.WARNING
            )

        message = (
            f'Drift detected in field "{field.field_name}" ({field.direction.value}). '
            f"{drift_result.metric_name} = {drift_result.metric_value} "
            f"(threshold: {threshold})."
        )

        return Notification(
            model_version_id=version.id,
            severity=severity,
            message=message,
        )

    @staticmethod
    def _extract_values_from_models(inferences: list[InferenceData], field: SchemaField) -> list:
        """Extract values for a single field from a list of inference records.

        Reads from ``inputs`` or ``outputs`` depending on the field's
        direction. ``None`` values are silently skipped.

        Args:
            inferences: Inference records to extract from.
            field: The schema field whose values should be collected.

        Returns:
            A list of non-None field values in the same order as the input
            records.
        """
        values = []
        for inf in inferences:
            data = inf.inputs if field.direction == FieldDirection.INPUT else inf.outputs
            val = data.get(field.field_name)
            if val is not None:
                values.append(val)
        return values

    @staticmethod
    def _extract_values_from_dicts_or_models(data_list: list, field: SchemaField) -> list:
        """Extract field values from either ReferenceData models or raw dicts."""
        values = []
        for item in data_list:
            if hasattr(item, "inputs"):
                data = item.inputs if field.direction == FieldDirection.INPUT else item.outputs
            else:
                data = item.get("inputs", {}) if field.direction == FieldDirection.INPUT else item.get("outputs", {})
            val = data.get(field.field_name)
            if val is not None:
                values.append(val)
        return values

    async def _get_job_config(self, job_id: uuid.UUID) -> JobConfig:
        result = await self.db.execute(select(JobConfig).where(JobConfig.id == job_id))
        config = result.scalar_one_or_none()
        if not config:
            raise HTTPException(status_code=404, detail="Job not found")
        return config

    async def _load_inferences_as_dicts(
        self,
        model_version_id: uuid.UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[InferenceData]:
        """Load inferences for the previous window (used as 'reference' in rolling_window mode)."""
        return await self.load_inferences(model_version_id, from_ts, to_ts)
