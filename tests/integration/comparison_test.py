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
    assert data["schema_diff"] == []

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


async def test_compare_histograms_share_edges_and_all_bins(client: AsyncClient):
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
    age_panel = next(p for p in resp.json()["data"]["panels"] if p["field_name"] == "age")
    buckets_a = age_panel["data_a"]["buckets"]
    buckets_b = age_panel["data_b"]["buckets"]

    assert len(buckets_a) == 20
    edges_a = [(b["range_start"], b["range_end"]) for b in buckets_a]
    assert edges_a == [(b["range_start"], b["range_end"]) for b in buckets_b]
    assert sum(b["count"] for b in buckets_a) == 10
    assert sum(b["count"] for b in buckets_b) == 10
    assert any(b["count"] == 0 for b in buckets_a)


async def _create_version_with_schema(client: AsyncClient, model_id: str, schema: list[dict]) -> str:
    resp = await client.post(f"/api/v1/models/{model_id}/versions", json={"version": "v2.0", "schema": schema})
    assert resp.status_code == 201
    return resp.json()["data"]["id"]


async def _ingest(client: AsyncClient, version_id: str, inputs: dict, outputs: dict, ts: datetime):
    resp = await client.post(
        "/api/v1/inferences",
        json={"model_version_id": version_id, "inputs": inputs, "outputs": outputs, "timestamp": ts.isoformat()},
    )
    assert resp.status_code in (200, 201)


def _vs_version_params(other_model_id: str, other_version_id: str, now: datetime) -> dict:
    return {
        "mode": "vs_version",
        "other_model_id": other_model_id,
        "other_version_id": other_version_id,
        "from_a": (now - timedelta(days=1)).isoformat(),
        "to_a": now.isoformat(),
        "from_b": (now - timedelta(days=1)).isoformat(),
        "to_b": now.isoformat(),
    }


async def test_compare_vs_version_across_models(client: AsyncClient):
    model_a = await create_model(client, name="vv-model-a")
    version_a = await create_version(client, model_a["id"])  # age, gender (in); score (out)
    model_b = await create_model(client, name="vv-model-b")
    version_b_id = await _create_version_with_schema(
        client,
        model_b["id"],
        [
            {"direction": "input", "field_name": "age", "data_type": "numerical"},
            {"direction": "input", "field_name": "gender", "data_type": "numerical"},  # type changed
            {"direction": "input", "field_name": "region", "data_type": "categorical"},  # only in b
            {"direction": "output", "field_name": "score", "data_type": "numerical"},
        ],
    )
    now = datetime.now(UTC)
    await _ingest(client, version_a["id"], {"age": 30, "gender": "male"}, {"score": 0.5}, now - timedelta(hours=1))
    await _ingest(
        client, version_b_id, {"age": 40, "gender": 1, "region": "eu"}, {"score": 0.9}, now - timedelta(hours=1)
    )

    resp = await client.get(
        f"/api/v1/models/{model_a['id']}/versions/{version_a['id']}/dashboard/compare",
        params=_vs_version_params(model_b["id"], version_b_id, now),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["model_version_id"] == version_a["id"]
    assert [p["field_name"] for p in data["panels"]] == ["age", "score"]
    age = data["panels"][0]
    assert age["data_a"]["statistics"]["mean"] == 30
    assert age["data_b"]["statistics"]["mean"] == 40
    assert data["schema_diff"] == [
        {
            "field_name": "gender",
            "direction": "input",
            "status": "type_changed",
            "data_type_a": "categorical",
            "data_type_b": "numerical",
        },
        {
            "field_name": "region",
            "direction": "input",
            "status": "only_in_b",
            "data_type_a": None,
            "data_type_b": "categorical",
        },
    ]


async def test_compare_vs_version_same_model(client: AsyncClient):
    model = await create_model(client, name="vv-same-model")
    version_a = await create_version(client, model["id"])
    version_b_id = await _create_version_with_schema(
        client,
        model["id"],
        [
            {"direction": "input", "field_name": "age", "data_type": "numerical"},
            {"direction": "output", "field_name": "score", "data_type": "numerical"},
        ],
    )

    resp = await client.get(
        f"/api/v1/models/{model['id']}/versions/{version_a['id']}/dashboard/compare",
        params=_vs_version_params(model["id"], version_b_id, datetime.now(UTC)),
    )
    data = resp.json()["data"]
    assert [p["field_name"] for p in data["panels"]] == ["age", "score"]
    assert [(d["direction"], d["field_name"], d["status"]) for d in data["schema_diff"]] == [
        ("input", "gender", "only_in_a"),
    ]


async def test_compare_vs_version_missing_params(client: AsyncClient):
    model = await create_model(client, name="vv-missing")
    version = await create_version(client, model["id"])

    resp = await client.get(
        f"/api/v1/models/{model['id']}/versions/{version['id']}/dashboard/compare",
        params={"mode": "vs_version", "from_a": datetime.now(UTC).isoformat()},
    )
    assert resp.status_code == 422


async def test_compare_vs_reference_has_empty_schema_diff(client: AsyncClient):
    model = await create_model(client, name="vr-diff")
    version = await create_version(client, model["id"])
    now = datetime.now(UTC)

    resp = await client.get(
        f"/api/v1/models/{model['id']}/versions/{version['id']}/dashboard/compare",
        params={"mode": "vs_reference", "from_a": (now - timedelta(days=1)).isoformat(), "to_a": now.isoformat()},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["schema_diff"] == []
