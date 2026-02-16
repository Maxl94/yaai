import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yaai.schemas.model import (
    FieldDirection,
    ModelCreate,
    ModelUpdate,
    ModelVersionCreate,
    ModelVersionUpdate,
    SchemaFieldCreate,
)
from yaai.server.models.inference import InferenceData
from yaai.server.models.job import DriftResult, JobConfig
from yaai.server.models.model import Model, ModelVersion, SchemaField

logger = logging.getLogger(__name__)


class ModelService:
    """Encapsulates CRUD and schema-management operations for ML models and their versions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_model(self, data: ModelCreate) -> Model:
        """Create a new model record.

        Args:
            data: Validated model creation payload.

        Returns:
            The newly created Model with eagerly loaded relations.
        """
        model = Model(name=data.name, description=data.description)
        self.db.add(model)
        await self.db.commit()
        return await self.get_model(model.id)

    async def list_models(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        model_ids: list[uuid.UUID] | None = None,
    ):
        """Return a paginated list of model summaries with inference counts.

        Args:
            page: 1-based page index.
            page_size: Maximum number of results per page.
            search: Optional case-insensitive name filter.
            model_ids: If provided, only return models with these IDs (SA filtering).

        Returns:
            A tuple of (list of summary dicts, total count).
        """
        query = select(Model).options(selectinload(Model.versions).selectinload(ModelVersion.schema_fields))
        if search:
            query = query.where(Model.name.ilike(f"%{search}%"))
        if model_ids is not None:
            query = query.where(Model.id.in_(model_ids))

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_query)).scalar_one()

        query = query.order_by(Model.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        models = result.scalars().unique().all()

        summaries = []
        for model in models:
            active_version = next((v for v in model.versions if v.is_active), None)

            inference_count = 0
            if model.versions:
                version_ids = [v.id for v in model.versions]
                count_q = select(func.count()).where(InferenceData.model_version_id.in_(version_ids))
                inference_count = (await self.db.execute(count_q)).scalar_one()

            summaries.append(
                {
                    "id": model.id,
                    "name": model.name,
                    "description": model.description,
                    "created_at": model.created_at,
                    "updated_at": model.updated_at,
                    "active_version": active_version,
                    "total_inferences": inference_count,
                }
            )

        return summaries, total

    async def get_model(self, model_id: uuid.UUID) -> Model:
        """Fetch a single model by ID, raising 404 if not found."""
        result = await self.db.execute(
            select(Model)
            .options(selectinload(Model.versions).selectinload(ModelVersion.schema_fields))
            .where(Model.id == model_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="Model not found")
        return model

    async def update_model(self, model_id: uuid.UUID, data: ModelUpdate) -> Model:
        """Partially update a model's name and/or description.

        Args:
            model_id: Primary key of the model to update.
            data: Fields to patch; ``None`` values are skipped.

        Returns:
            The refreshed Model after committing changes.

        Raises:
            HTTPException: 404 if the model does not exist.
        """
        model = await self.get_model(model_id)
        if data.name is not None:
            model.name = data.name
        if data.description is not None:
            model.description = data.description
        await self.db.commit()
        return await self.get_model(model_id)

    async def delete_model(self, model_id: uuid.UUID) -> None:
        """Delete a model and all associated versions via cascade.

        Args:
            model_id: Primary key of the model to delete.

        Raises:
            HTTPException: 404 if the model does not exist.
        """
        model = await self.get_model(model_id)
        await self.db.delete(model)
        await self.db.commit()

    async def create_version(self, model_id: uuid.UUID, data: ModelVersionCreate) -> ModelVersion:
        """Create a new model version with schema fields.

        By default, all previously active versions (and their jobs) are
        deactivated unless ``data.keep_previous_active`` is set.

        Args:
            model_id: Parent model ID.
            data: Version payload including schema fields and options.

        Returns:
            The fully loaded ModelVersion with its schema fields.

        Raises:
            HTTPException: 404 if the parent model does not exist, or 422 if
                schema validation fails.
        """
        await self.get_model(model_id)
        self._validate_schema_fields(data.schema_fields)

        # Auto-deactivate previous versions and their jobs (unless opted out)
        if not data.keep_previous_active:
            # Get IDs of currently active versions for this model
            active_versions = await self.db.execute(
                select(ModelVersion.id).where(
                    ModelVersion.model_id == model_id,
                    ModelVersion.is_active == True,  # noqa: E712
                )
            )
            active_version_ids = [row[0] for row in active_versions.all()]

            if active_version_ids:
                # Deactivate old versions
                await self.db.execute(
                    update(ModelVersion).where(ModelVersion.id.in_(active_version_ids)).values(is_active=False)
                )
                # Deactivate jobs belonging to old versions
                await self.db.execute(
                    update(JobConfig).where(JobConfig.model_version_id.in_(active_version_ids)).values(is_active=False)
                )

        version = ModelVersion(
            model_id=model_id,
            version=data.version,
            description=data.description,
            is_active=True,
        )
        self.db.add(version)
        await self.db.flush()

        for field_data in data.schema_fields:
            field = SchemaField(
                model_version_id=version.id,
                direction=field_data.direction,
                field_name=field_data.field_name,
                data_type=field_data.data_type,
                drift_metric=field_data.drift_metric,
                alert_threshold=field_data.alert_threshold,
            )
            self.db.add(field)

        # Always create a default drift detection job for the new version
        model = await self.get_model(model_id)
        default_job = JobConfig(
            model_version_id=version.id,
            name=f"{model.name} Daily Drift Check",
            schedule="0 2 * * *",  # Daily at 2 AM
            comparison_type="vs_reference",
            window_size="7d",
            is_active=True,
        )
        self.db.add(default_job)

        await self.db.commit()

        return await self.get_version(model_id, version.id)

    async def get_version(self, model_id: uuid.UUID, version_id: uuid.UUID) -> ModelVersion:
        """Fetch a single model version by ID, raising 404 if not found."""
        result = await self.db.execute(
            select(ModelVersion)
            .options(selectinload(ModelVersion.schema_fields))
            .where(ModelVersion.id == version_id, ModelVersion.model_id == model_id)
        )
        version = result.scalar_one_or_none()
        if not version:
            raise HTTPException(status_code=404, detail="Model version not found")
        return version

    async def update_version(
        self, model_id: uuid.UUID, version_id: uuid.UUID, data: ModelVersionUpdate
    ) -> ModelVersion:
        """Partially update a version's description or active status.

        Args:
            model_id: Parent model ID.
            version_id: Version to update.
            data: Fields to patch; ``None`` values are skipped.

        Returns:
            The refreshed ModelVersion after committing changes.

        Raises:
            HTTPException: 404 if the version does not exist.
        """
        version = await self.get_version(model_id, version_id)
        if data.description is not None:
            version.description = data.description
        if data.is_active is not None:
            version.is_active = data.is_active
        await self.db.commit()
        return await self.get_version(model_id, version_id)

    async def update_field_threshold(
        self,
        model_id: uuid.UUID,
        version_id: uuid.UUID,
        field_id: uuid.UUID,
        alert_threshold: float | None,
    ) -> SchemaField:
        """Update the alert threshold on a single schema field.

        This is always allowed, even when drift results already exist for the
        version (unlike a full schema overwrite).

        Args:
            model_id: Parent model ID.
            version_id: Version owning the field.
            field_id: Schema field to update.
            alert_threshold: New threshold value, or ``None`` to clear it.

        Returns:
            The updated SchemaField.

        Raises:
            HTTPException: 404 if the version or field does not exist.
        """
        await self.get_version(model_id, version_id)
        result = await self.db.execute(
            select(SchemaField).where(
                SchemaField.id == field_id,
                SchemaField.model_version_id == version_id,
            )
        )
        field = result.scalar_one_or_none()
        if not field:
            raise HTTPException(status_code=404, detail="Schema field not found")
        field.alert_threshold = alert_threshold
        await self.db.commit()
        await self.db.refresh(field)
        return field

    async def overwrite_schema(
        self, model_id: uuid.UUID, version_id: uuid.UUID, fields: list[SchemaFieldCreate]
    ) -> ModelVersion:
        """Replace all schema fields on a version with a new set.

        The operation is rejected if drift results already exist for the
        version; callers should create a new version instead.

        Args:
            model_id: Parent model ID.
            version_id: Version whose schema will be replaced.
            fields: Complete list of new schema fields.

        Returns:
            The refreshed ModelVersion with updated schema fields.

        Raises:
            HTTPException: 409 if drift results exist (schema locked), 404 if
                the version is missing, or 422 if validation fails.
        """
        version = await self.get_version(model_id, version_id)

        if not await self._can_overwrite_schema(version_id):
            raise HTTPException(
                status_code=409,
                detail="Schema is locked — drift results exist. Create a new version instead.",
            )

        self._validate_schema_fields(fields)

        for existing_field in version.schema_fields:
            await self.db.delete(existing_field)

        for field_data in fields:
            field = SchemaField(
                model_version_id=version.id,
                direction=field_data.direction,
                field_name=field_data.field_name,
                data_type=field_data.data_type,
                drift_metric=field_data.drift_metric,
                alert_threshold=field_data.alert_threshold,
            )
            self.db.add(field)

        await self.db.commit()
        await self.db.refresh(version, attribute_names=["schema_fields"])
        return version

    @staticmethod
    def _validate_schema_fields(fields: list[SchemaFieldCreate]) -> None:
        has_input = any(f.direction == FieldDirection.INPUT for f in fields)
        has_output = any(f.direction == FieldDirection.OUTPUT for f in fields)
        if not has_input or not has_output:
            raise HTTPException(
                status_code=422,
                detail="Schema must have at least one input and one output field",
            )

        seen = set()
        for f in fields:
            key = (f.direction, f.field_name)
            if key in seen:
                raise HTTPException(
                    status_code=422,
                    detail=f"Duplicate field: {f.field_name} ({f.direction.value})",
                )
            seen.add(key)

    async def _can_overwrite_schema(self, version_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(func.count())
            .select_from(DriftResult)
            .join(DriftResult.job_run)
            .join(JobConfig)
            .where(JobConfig.model_version_id == version_id)
        )
        return result.scalar_one() == 0
