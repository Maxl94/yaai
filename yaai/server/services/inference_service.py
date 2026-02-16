import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.schemas.model import SchemaFieldCreate
from yaai.server.models.inference import GroundTruth, InferenceData, ReferenceData
from yaai.server.models.job import JobConfig
from yaai.server.models.model import SchemaField
from yaai.server.services.base import BaseService
from yaai.server.services.schema_helpers import validate_record


class InferenceService(BaseService):
    """Manages inference data lifecycle including ingestion, querying, and ground truth."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def create_inference(
        self,
        model_version_id: uuid.UUID,
        inputs: dict,
        outputs: dict,
        timestamp: datetime | None = None,
    ) -> InferenceData:
        """Validate and store a single inference record."""
        version = await self.get_version_with_schema(model_version_id)
        self._validate_data(version.schema_fields, inputs, outputs)

        inference = InferenceData(
            model_version_id=model_version_id,
            inputs=inputs,
            outputs=outputs,
            timestamp=timestamp or datetime.now(UTC),
        )
        self.db.add(inference)
        await self.db.commit()
        await self.db.refresh(inference)
        return inference

    async def create_inference_batch(
        self,
        model_version_id: uuid.UUID,
        records: list[dict],
    ) -> dict:
        """Ingest a batch of inference records, collecting per-record errors.

        Returns:
            Dict with 'ingested' count, 'failed' count, and 'errors' list.
        """
        version = await self.get_version_with_schema(model_version_id)

        ingested = 0
        errors = []

        for i, record in enumerate(records):
            try:
                inputs = record.get("inputs", {})
                outputs = record.get("outputs", {})
                timestamp = record.get("timestamp")

                self._validate_data(version.schema_fields, inputs, outputs)

                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)

                inference = InferenceData(
                    model_version_id=model_version_id,
                    inputs=inputs,
                    outputs=outputs,
                    timestamp=timestamp or datetime.now(UTC),
                )
                self.db.add(inference)
                ingested += 1
            except (HTTPException, ValueError) as e:
                detail = e.detail if isinstance(e, HTTPException) else str(e)
                errors.append(f"Record {i}: {detail}")

        await self.db.commit()
        return {"ingested": ingested, "failed": len(errors), "errors": errors}

    async def list_inferences(
        self,
        model_version_id: uuid.UUID,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ):
        """List inferences for a model version with optional time filtering and pagination."""
        query = select(InferenceData).where(InferenceData.model_version_id == model_version_id)
        if from_ts:
            query = query.where(InferenceData.timestamp >= from_ts)
        if to_ts:
            query = query.where(InferenceData.timestamp <= to_ts)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        query = query.order_by(InferenceData.timestamp.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        return result.scalars().all(), total

    async def get_inference_volume(
        self,
        model_version_id: uuid.UUID,
        bucket: str = "day",
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
    ) -> list[dict]:
        """Return time-bucketed inference counts."""
        trunc_col = func.date_trunc(bucket, InferenceData.timestamp)
        query = select(trunc_col.label("bucket"), func.count().label("count")).where(
            InferenceData.model_version_id == model_version_id
        )
        if from_ts:
            query = query.where(InferenceData.timestamp >= from_ts)
        if to_ts:
            query = query.where(InferenceData.timestamp <= to_ts)
        query = query.group_by(trunc_col).order_by(trunc_col)

        result = await self.db.execute(query)
        return [{"bucket": row.bucket.isoformat(), "count": row.count} for row in result.all()]

    async def upload_reference_data(
        self,
        model_id: uuid.UUID,
        version_id: uuid.UUID,
        records: list[dict],
    ) -> int:
        """Replace reference data for a model version and reactivate inactive drift jobs.

        Returns:
            Number of reference records ingested.
        """
        version = await self.get_version_with_schema(version_id)
        if version.model_id != model_id:
            raise HTTPException(status_code=404, detail="Model version not found")

        await self.db.execute(delete(ReferenceData).where(ReferenceData.model_version_id == version_id))

        count = 0
        for record in records:
            inputs = record.get("inputs", {})
            outputs = record.get("outputs", {})
            self._validate_data(version.schema_fields, inputs, outputs)

            ref = ReferenceData(
                model_version_id=version_id,
                inputs=inputs,
                outputs=outputs,
            )
            self.db.add(ref)
            count += 1

        # Auto-activate inactive drift jobs
        result = await self.db.execute(
            select(JobConfig).where(
                JobConfig.model_version_id == version_id,
                JobConfig.is_active == False,  # noqa: E712
            )
        )
        for job in result.scalars().all():
            job.is_active = True

        await self.db.commit()
        return count

    async def create_ground_truth(
        self,
        inference_id: uuid.UUID,
        label: dict,
        timestamp: datetime | None = None,
    ) -> GroundTruth:
        """Attach a ground-truth label to an existing inference record."""
        result = await self.db.execute(select(InferenceData).where(InferenceData.id == inference_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Inference not found")

        gt = GroundTruth(
            inference_id=inference_id,
            label=label,
            timestamp=timestamp or datetime.now(UTC),
        )
        self.db.add(gt)
        await self.db.commit()
        await self.db.refresh(gt)
        return gt

    @staticmethod
    def _validate_data(schema_fields: list[SchemaField], inputs: dict, outputs: dict) -> None:
        """Validate inputs/outputs against schema, raising on first error."""
        pydantic_fields = [
            SchemaFieldCreate(
                direction=f.direction,
                field_name=f.field_name,
                data_type=f.data_type,
                drift_metric=f.drift_metric,
                alert_threshold=f.alert_threshold,
            )
            for f in schema_fields
        ]
        result = validate_record(pydantic_fields, inputs, outputs)
        if not result.valid:
            # Raise on first error to match existing behavior
            for field_result in result.fields:
                if field_result.status == "missing":
                    raise HTTPException(
                        status_code=422,
                        detail=f"Missing required field: {field_result.field_name} ({field_result.direction.value})",
                    )
                if field_result.status == "error":
                    raise HTTPException(status_code=422, detail=field_result.error)
