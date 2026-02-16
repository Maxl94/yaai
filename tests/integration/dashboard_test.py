from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.conftest import create_model, create_version


async def _setup_with_data(client: AsyncClient):
    """Create model + version + ingest inference data."""
    model = await create_model(client, name="dashboard-model")
    version = await create_version(client, model["id"])
    model_id = model["id"]
    version_id = version["id"]

    now = datetime.now(UTC)
    for i in range(10):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 20 + i * 5, "gender": ["male", "female"][i % 2]},
                "outputs": {"score": 0.1 * i + 0.1},
                "timestamp": (now - timedelta(hours=i)).isoformat(),
            },
        )

    return model_id, version_id


async def test_dashboard_returns_panels(client: AsyncClient):
    model_id, version_id = await _setup_with_data(client)
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/dashboard")
    assert resp.status_code == 200

    data = resp.json()["data"]
    assert data["model_version_id"] == version_id
    panels = data["panels"]
    # Schema has 3 fields: age (numerical input), gender (categorical input), score (numerical output)
    assert len(panels) == 3

    field_names = [p["field_name"] for p in panels]
    assert "age" in field_names
    assert "gender" in field_names
    assert "score" in field_names


async def test_dashboard_panel_ordering(client: AsyncClient):
    model_id, version_id = await _setup_with_data(client)
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/dashboard")
    panels = resp.json()["data"]["panels"]

    # Inputs first (age, gender alphabetically), then outputs (score)
    assert panels[0]["field_name"] == "age"
    assert panels[0]["direction"] == "input"
    assert panels[1]["field_name"] == "gender"
    assert panels[1]["direction"] == "input"
    assert panels[2]["field_name"] == "score"
    assert panels[2]["direction"] == "output"


async def test_numerical_panel_structure(client: AsyncClient):
    model_id, version_id = await _setup_with_data(client)
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/dashboard")
    panels = resp.json()["data"]["panels"]
    age_panel = next(p for p in panels if p["field_name"] == "age")

    assert age_panel["chart_type"] == "histogram"
    assert age_panel["data_type"] == "numerical"

    data = age_panel["data"]
    assert "buckets" in data
    assert len(data["buckets"]) > 0
    assert "range_start" in data["buckets"][0]
    assert "range_end" in data["buckets"][0]
    assert "count" in data["buckets"][0]

    stats = data["statistics"]
    assert stats["count"] == 10
    assert stats["null_count"] == 0
    assert stats["min"] == 20
    assert stats["max"] == 65


async def test_categorical_panel_structure(client: AsyncClient):
    model_id, version_id = await _setup_with_data(client)
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/dashboard")
    panels = resp.json()["data"]["panels"]
    gender_panel = next(p for p in panels if p["field_name"] == "gender")

    assert gender_panel["chart_type"] == "bar"
    assert gender_panel["data_type"] == "categorical"

    data = gender_panel["data"]
    assert "categories" in data
    assert len(data["categories"]) == 2  # male, female

    stats = data["statistics"]
    assert stats["total_count"] == 10
    assert stats["unique_count"] == 2
    assert stats["null_count"] == 0


async def test_dashboard_empty_no_inferences(client: AsyncClient):
    model = await create_model(client, name="empty-dash")
    version = await create_version(client, model["id"])
    resp = await client.get(f"/api/v1/models/{model['id']}/versions/{version['id']}/dashboard")
    assert resp.status_code == 200

    panels = resp.json()["data"]["panels"]
    assert len(panels) == 3

    age_panel = next(p for p in panels if p["field_name"] == "age")
    assert age_panel["data"]["statistics"]["count"] == 0
    assert age_panel["data"]["buckets"] == []


async def test_dashboard_time_range_filter(client: AsyncClient):
    model_id, version_id = await _setup_with_data(client)
    now = datetime.now(UTC)

    # Only get last 3 hours of data
    from_ts = (now - timedelta(hours=3)).isoformat()
    resp = await client.get(
        f"/api/v1/models/{model_id}/versions/{version_id}/dashboard",
        params={"from": from_ts},
    )
    assert resp.status_code == 200
    panels = resp.json()["data"]["panels"]
    age_panel = next(p for p in panels if p["field_name"] == "age")
    # Should have fewer than 10 inferences
    assert age_panel["data"]["statistics"]["count"] < 10


async def test_dashboard_not_found(client: AsyncClient):
    resp = await client.get(
        "/api/v1/models/00000000-0000-0000-0000-000000000000/versions/00000000-0000-0000-0000-000000000000/dashboard"
    )
    assert resp.status_code == 404
