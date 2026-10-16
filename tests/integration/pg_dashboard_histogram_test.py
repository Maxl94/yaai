"""PostgreSQL coverage for the SQL histogram path of the dashboard service."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_model, create_version
from yaai.server.models.inference import InferenceData
from yaai.server.services.histogram import build_histogram


async def _seed_ages(client: AsyncClient, db: AsyncSession, ages: list[float | None]) -> tuple[str, str]:
    model = await create_model(client, name="pg-hist-model")
    version = await create_version(client, model["id"])
    now = datetime.now(UTC)
    db.add_all(
        InferenceData(
            model_version_id=version["id"],
            inputs={"age": age, "gender": "male"},
            outputs={"score": 0.5},
            timestamp=now - timedelta(minutes=i),
        )
        for i, age in enumerate(ages)
    )
    await db.commit()
    return model["id"], version["id"]


async def _age_buckets(client: AsyncClient, model_id: str, version_id: str) -> list[dict]:
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/dashboard")
    assert resp.status_code == 200
    panel = next(p for p in resp.json()["data"]["panels"] if p["field_name"] == "age")
    return panel["data"]["buckets"]


def _expected(ages: list[float]) -> list[dict]:
    return [b.model_dump() for b in build_histogram(np.array(ages, dtype=float))]


def _assert_equivalent(actual: list[dict], expected: list[dict]) -> None:
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected, strict=True):
        assert got["is_underflow"] == want["is_underflow"]
        assert got["is_overflow"] == want["is_overflow"]
        assert got["range_start"] == pytest.approx(want["range_start"], rel=1e-5, abs=1e-9)
        assert got["range_end"] == pytest.approx(want["range_end"], rel=1e-5, abs=1e-9)
        assert got["count"] == want["count"]


async def test_sql_histogram_outlier_matches_python_helper(owner_client: AsyncClient, pg_db: AsyncSession):
    rng = np.random.default_rng(42)
    ages = [float(x) for x in rng.normal(50, 5, 300)] + [100000.0]
    model_id, version_id = await _seed_ages(owner_client, pg_db, ages)

    buckets = await _age_buckets(owner_client, model_id, version_id)

    assert buckets[-1]["is_overflow"] is True
    assert buckets[-1]["range_end"] == 100000.0
    assert sum(b["count"] for b in buckets) == 301
    _assert_equivalent(buckets, _expected(ages))


async def test_sql_histogram_returns_empty_buckets_for_gaps(owner_client: AsyncClient, pg_db: AsyncSession):
    ages = [0.0] * 20 + [100.0] * 20
    model_id, version_id = await _seed_ages(owner_client, pg_db, ages)

    buckets = await _age_buckets(owner_client, model_id, version_id)

    assert len(buckets) == 20
    assert buckets[0]["count"] == 20
    assert buckets[-1]["count"] == 20
    assert all(b["count"] == 0 for b in buckets[1:-1])
    _assert_equivalent(buckets, _expected(ages))


async def test_sql_histogram_without_outliers_matches_python_helper(owner_client: AsyncClient, pg_db: AsyncSession):
    ages = [float(x) for x in np.random.default_rng(7).uniform(0.001, 0.01, 150)]
    model_id, version_id = await _seed_ages(owner_client, pg_db, ages)

    buckets = await _age_buckets(owner_client, model_id, version_id)

    assert len(buckets) == 20
    _assert_equivalent(buckets, _expected(ages))


async def test_sql_histogram_constant_values_single_bucket(owner_client: AsyncClient, pg_db: AsyncSession):
    model_id, version_id = await _seed_ages(owner_client, pg_db, [7.0] * 5)

    buckets = await _age_buckets(owner_client, model_id, version_id)

    assert len(buckets) == 1
    assert buckets[0]["count"] == 5
    assert (buckets[0]["range_start"], buckets[0]["range_end"]) == (7.0, 7.0)


async def test_sql_histogram_no_data_returns_no_buckets(owner_client: AsyncClient, pg_db: AsyncSession):
    model_id, version_id = await _seed_ages(owner_client, pg_db, [])

    assert await _age_buckets(owner_client, model_id, version_id) == []
