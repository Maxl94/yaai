"""Base service class with common database operations."""

import uuid
from collections import Counter
from datetime import datetime
from statistics import median

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from yaai.schemas.model import FieldDirection
from yaai.server.models.inference import InferenceData, ReferenceData
from yaai.server.models.model import ModelVersion, SchemaField
from yaai.server.schemas.dashboard import (
    CategoricalStatistics,
    CategoryCount,
    HistogramBucket,
    NumericalStatistics,
)


class BaseService:
    """Base class for all services with common database operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_version_with_schema(self, version_id: uuid.UUID) -> ModelVersion:
        """Load a model version with its schema fields eagerly loaded.

        Args:
            version_id: The UUID of the model version.

        Returns:
            The ModelVersion with schema_fields populated.

        Raises:
            HTTPException: 404 if version not found.
        """
        result = await self.db.execute(
            select(ModelVersion).options(selectinload(ModelVersion.schema_fields)).where(ModelVersion.id == version_id)
        )
        version = result.scalar_one_or_none()
        if not version:
            raise HTTPException(status_code=404, detail="Model version not found")
        return version

    async def load_inferences(
        self,
        model_version_id: uuid.UUID,
        from_ts: datetime,
        to_ts: datetime,
    ) -> list[InferenceData]:
        """Load inference data within a time range.

        Args:
            model_version_id: The model version to query.
            from_ts: Start of time range (inclusive).
            to_ts: End of time range (inclusive).

        Returns:
            List of InferenceData ordered by timestamp.
        """
        query = (
            select(InferenceData)
            .where(
                InferenceData.model_version_id == model_version_id,
                InferenceData.timestamp >= from_ts,
                InferenceData.timestamp <= to_ts,
            )
            .order_by(InferenceData.timestamp)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def load_reference_data(self, model_version_id: uuid.UUID) -> list[ReferenceData]:
        """Load all reference data for a model version.

        Args:
            model_version_id: The model version to query.

        Returns:
            List of ReferenceData records.
        """
        result = await self.db.execute(select(ReferenceData).where(ReferenceData.model_version_id == model_version_id))
        return list(result.scalars().all())

    @staticmethod
    def raise_not_found(resource_type: str = "Resource") -> None:
        """Raise a standard 404 HTTPException.

        Args:
            resource_type: Name of the resource for the error message.

        Raises:
            HTTPException: Always raises 404.
        """
        raise HTTPException(status_code=404, detail=f"{resource_type} not found")

    @staticmethod
    def extract_field_value(
        item: InferenceData | ReferenceData | dict,
        field: SchemaField,
    ):
        """Extract a field value from an inference/reference record.

        Args:
            item: An InferenceData, ReferenceData, or dict with inputs/outputs.
            field: The schema field to extract.

        Returns:
            The value of the field, or None if not present.
        """
        if hasattr(item, "inputs"):
            data = item.inputs if field.direction == FieldDirection.INPUT else item.outputs
        else:
            data = item.get("inputs", {}) if field.direction == FieldDirection.INPUT else item.get("outputs", {})
        return data.get(field.field_name)

    @staticmethod
    def extract_field_values(data_list: list, field: SchemaField) -> list:
        """Extract field values from a list of inference/reference records.

        Args:
            data_list: List of InferenceData, ReferenceData, or dicts.
            field: The schema field to extract.

        Returns:
            List of values (may include None for missing values).
        """
        return [BaseService.extract_field_value(item, field) for item in data_list]

    @staticmethod
    def sort_schema_fields(fields: list[SchemaField]) -> list[SchemaField]:
        """Sort schema fields: inputs first, then outputs; alphabetical within each group."""
        return sorted(
            fields,
            key=lambda f: (0 if f.direction == FieldDirection.INPUT else 1, f.field_name),
        )

    @staticmethod
    def build_histogram_buckets(edges: np.ndarray, counts: np.ndarray) -> list[HistogramBucket]:
        """Build histogram buckets from numpy edges and counts arrays."""
        return [
            HistogramBucket(
                range_start=round(float(edges[i]), 4),
                range_end=round(float(edges[i + 1]), 4),
                count=int(counts[i]),
            )
            for i in range(len(edges) - 1)
        ]

    @staticmethod
    def compute_numerical_statistics(
        arr: np.ndarray,
        values: list,
        null_count: int,
    ) -> NumericalStatistics:
        """Compute numerical statistics from a numpy array."""
        return NumericalStatistics(
            mean=round(float(arr.mean()), 4),
            median=round(float(median(values)), 4),
            std=round(float(arr.std()), 4),
            min=round(float(arr.min()), 4),
            max=round(float(arr.max()), 4),
            count=len(values),
            null_count=null_count,
        )

    @staticmethod
    def build_category_counts(values: list) -> tuple[list[CategoryCount], CategoricalStatistics]:
        """Build category counts and statistics from a list of categorical values.

        Args:
            values: Non-null categorical values.

        Returns:
            Tuple of (list of CategoryCount, CategoricalStatistics).
        """
        if not values:
            stats = CategoricalStatistics(
                unique_count=0,
                total_count=0,
                null_count=0,
                top_category=None,
            )
            return [], stats

        counter = Counter(values)
        total = len(values)
        categories = [
            CategoryCount(value=str(v), count=c, percentage=round(c / total * 100, 2)) for v, c in counter.most_common()
        ]
        top = counter.most_common(1)[0][0] if counter else None

        stats = CategoricalStatistics(
            unique_count=len(counter),
            total_count=total,
            null_count=0,
            top_category=str(top) if top is not None else None,
        )
        return categories, stats
