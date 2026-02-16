"""Pydantic schemas for dashboard panels, histograms, and statistics."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class NumericalStatistics(BaseModel):
    mean: float
    median: float
    std: float
    min: float
    max: float
    count: int
    null_count: int


class HistogramBucket(BaseModel):
    range_start: float
    range_end: float
    count: int


class HistogramData(BaseModel):
    buckets: list[HistogramBucket]
    statistics: NumericalStatistics


class CategoryCount(BaseModel):
    value: str
    count: int
    percentage: float


class CategoricalStatistics(BaseModel):
    unique_count: int
    total_count: int
    null_count: int
    top_category: str | None


class CategoricalData(BaseModel):
    categories: list[CategoryCount]
    statistics: CategoricalStatistics


class LatestDrift(BaseModel):
    metric_name: str
    metric_value: float
    is_drifted: bool
    calculated_at: datetime | None = None


class DashboardPanel(BaseModel):
    field_name: str
    direction: str
    data_type: str
    chart_type: str
    data: HistogramData | CategoricalData
    latest_drift: LatestDrift | None = None


class DashboardResponse(BaseModel):
    model_version_id: uuid.UUID
    time_range: dict
    panels: list[DashboardPanel]
