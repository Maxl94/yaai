from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.conftest import create_model, create_version


async def _setup_with_two_periods(client: AsyncClient):
    """Create model + version + ingest data in two distinct time periods."""
    model = await create_model(client, name="compare-model")
    version = await create_version(client, model["id"])
    model_id = model["id"]
    version_id = version["id"]

    now = datetime.now(UTC)

    # Period B (older): ages 20-30
    for i in range(10):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 20 + i, "gender": "male"},
                "outputs": {"score": 0.3},
                "timestamp": (now - timedelta(days=3, hours=i)).isoformat(),
            },
        )

    # Period A (recent): ages 50-60
    for i in range(10):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 50 + i, "gender": "female"},
                "outputs": {"score": 0.8},
                "timestamp": (now - timedelta(hours=i)).isoformat(),
            },
        )

    return model_id, version_id, now


async def test_compare_time_windows(client: AsyncClient):
    model_id, version_id, now = await _setup_with_two_periods(client)

    resp = await client.get(
        f"/api/v1/models/{model_id}/versions/{version_id}/dashboard/compare",
        params={
            "mode": "time_window",
            "from_a": (now - timedelta(days=1)).isoformat(),
            "to_a": now.isoformat(),
            "from_b": (now - timedelta(days=4)).isoformat(),
            "to_b": (now - timedelta(days=2)).isoformat(),
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    panels = data["panels"]
    assert len(panels) == 3  # age, gender, score

    # Each panel should have data_a and data_b
    for panel in panels:
        assert "data_a" in panel
        assert "data_b" in panel


async def test_compare_includes_drift_score(client: AsyncClient):
    model_id, version_id, now = await _setup_with_two_periods(client)

    resp = await client.get(
        f"/api/v1/models/{model_id}/versions/{version_id}/dashboard/compare",
        params={
            "mode": "time_window",
            "from_a": (now - timedelta(days=1)).isoformat(),
            "to_a": now.isoformat(),
            "from_b": (now - timedelta(days=4)).isoformat(),
            "to_b": (now - timedelta(days=2)).isoformat(),
        },
    )
    panels = resp.json()["data"]["panels"]
    age_panel = next(p for p in panels if p["field_name"] == "age")
    assert "drift_score" in age_panel
    assert "metric_name" in age_panel["drift_score"]
    assert "metric_value" in age_panel["drift_score"]
    assert "is_drifted" in age_panel["drift_score"]


async def test_compare_vs_reference(client: AsyncClient):
    model = await create_model(client, name="ref-compare")
    version = await create_version(client, model["id"])
    model_id = model["id"]
    version_id = version["id"]

    # Upload reference data
    await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
        json={"records": [{"inputs": {"age": 25 + i, "gender": "male"}, "outputs": {"score": 0.5}} for i in range(20)]},
    )

    # Ingest inference data
    now = datetime.now(UTC)
    for i in range(10):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 30 + i, "gender": "female"},
                "outputs": {"score": 0.7},
                "timestamp": (now - timedelta(hours=i)).isoformat(),
            },
        )

    resp = await client.get(
        f"/api/v1/models/{model_id}/versions/{version_id}/dashboard/compare",
        params={
            "mode": "vs_reference",
            "from_a": (now - timedelta(days=1)).isoformat(),
            "to_a": now.isoformat(),
        },
    )
    assert resp.status_code == 200
    panels = resp.json()["data"]["panels"]
    assert len(panels) == 3


async def test_compare_empty_period(client: AsyncClient):
    model = await create_model(client, name="empty-compare")
    version = await create_version(client, model["id"])
    model_id = model["id"]
    version_id = version["id"]

    now = datetime.now(UTC)

    # Only ingest data in period A
    for i in range(5):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 30 + i, "gender": "male"},
                "outputs": {"score": 0.5},
                "timestamp": (now - timedelta(hours=i)).isoformat(),
            },
        )

    resp = await client.get(
        f"/api/v1/models/{model_id}/versions/{version_id}/dashboard/compare",
        params={
            "mode": "time_window",
            "from_a": (now - timedelta(days=1)).isoformat(),
            "to_a": now.isoformat(),
            "from_b": (now - timedelta(days=10)).isoformat(),
            "to_b": (now - timedelta(days=9)).isoformat(),
        },
    )
    assert resp.status_code == 200
    panels = resp.json()["data"]["panels"]
    # Period B is empty - panels should still exist
    age_panel = next(p for p in panels if p["field_name"] == "age")
    assert age_panel["data_b"]["statistics"]["count"] == 0


async def test_compare_missing_params(client: AsyncClient):
    model = await create_model(client, name="missing-params")
    version = await create_version(client, model["id"])

    resp = await client.get(
        f"/api/v1/models/{model['id']}/versions/{version['id']}/dashboard/compare",
        params={"mode": "time_window", "from_a": datetime.now(UTC).isoformat()},
    )
    assert resp.status_code == 422
