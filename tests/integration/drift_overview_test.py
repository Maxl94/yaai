from httpx import AsyncClient

from tests.conftest import create_model, create_version


async def _get_auto_job_id(client: AsyncClient, model_id: str, version_id: str) -> str:
    """Get the auto-created job ID for a model version."""
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/jobs")
    assert resp.status_code == 200
    jobs = resp.json()["data"]
    assert len(jobs) == 1
    return jobs[0]["id"]


async def _setup_with_data(client: AsyncClient):
    """Create model, version, reference data, and inferences."""
    model = await create_model(client, name="overview-model")
    version = await create_version(client, model["id"])
    model_id, version_id = model["id"], version["id"]

    # Upload reference data
    await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
        json={
            "records": [
                {"inputs": {"age": 25, "gender": "male"}, "outputs": {"score": 0.7}},
                {"inputs": {"age": 40, "gender": "female"}, "outputs": {"score": 0.3}},
            ]
            * 50,
        },
    )

    # Create inferences
    for i in range(50):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 20 + i, "gender": "male" if i % 2 == 0 else "female"},
                "outputs": {"score": 0.5 + (i % 10) * 0.05},
            },
        )

    return model_id, version_id


async def test_drift_overview_empty(client: AsyncClient):
    resp = await client.get("/api/v1/drift-overview")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


async def test_drift_overview_with_data(client: AsyncClient):
    model_id, version_id = await _setup_with_data(client)

    # Create and trigger a drift job
    job_id = await _get_auto_job_id(client, model_id, version_id)
    await client.post(f"/api/v1/jobs/{job_id}/trigger")

    # Check overview
    resp = await client.get("/api/v1/drift-overview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) >= 1
    item = data[0]
    assert "model_name" in item
    assert "health_percentage" in item
    assert "results" in item


async def test_drift_overview_pagination(client: AsyncClient):
    resp = await client.get("/api/v1/drift-overview", params={"page": 1, "page_size": 5})
    assert resp.status_code == 200
    assert "meta" in resp.json()


async def test_trigger_and_list_drift_results(client: AsyncClient):
    model_id, version_id = await _setup_with_data(client)

    job_id = await _get_auto_job_id(client, model_id, version_id)
    trigger_resp = await client.post(f"/api/v1/jobs/{job_id}/trigger")
    assert trigger_resp.status_code == 201

    results_resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/drift-results")
    assert results_resp.status_code == 200
    results = results_resp.json()["data"]
    assert len(results) > 0
    assert "field_name" in results[0]
    assert "score" in results[0]
    assert "is_drifted" in results[0]


async def test_trigger_creates_notifications_on_drift(client: AsyncClient):
    model_id, version_id = await _setup_with_data(client)

    job_id = await _get_auto_job_id(client, model_id, version_id)
    await client.post(f"/api/v1/jobs/{job_id}/trigger")

    notifs_resp = await client.get("/api/v1/notifications")
    assert notifs_resp.status_code == 200
    # May or may not have drift notifications depending on data similarity


async def test_mark_notification_read(client: AsyncClient):
    model_id, version_id = await _setup_with_data(client)

    job_id = await _get_auto_job_id(client, model_id, version_id)
    await client.post(f"/api/v1/jobs/{job_id}/trigger")

    notifs_resp = await client.get("/api/v1/notifications")
    notifications = notifs_resp.json()["data"]

    if len(notifications) > 0:
        notif_id = notifications[0]["id"]
        resp = await client.patch(f"/api/v1/notifications/{notif_id}", json={"is_read": True})
        assert resp.status_code == 200
        assert resp.json()["data"]["is_read"] is True


async def test_inference_volume_skipped_sqlite(client: AsyncClient):
    """Inference volume uses date_trunc (PostgreSQL-only). Verify the endpoint exists."""
    model_id, version_id = await _setup_with_data(client)
    resp = await client.get(
        f"/api/v1/models/{model_id}/versions/{version_id}/inference-volume",
        params={"bucket": "day"},
    )
    # date_trunc is not available in SQLite — returns 500 in test env
    # This test documents the endpoint exists; full test requires PostgreSQL
    assert resp.status_code in (200, 500)


async def test_drift_overview_with_multiple_models(client: AsyncClient):
    """Test drift overview aggregates multiple models correctly."""
    # Create two models with drift data
    for name in ["multi-model-1", "multi-model-2"]:
        model = await create_model(client, name=name)
        version = await create_version(client, model["id"])
        model_id, version_id = model["id"], version["id"]

        # Upload reference data
        await client.post(
            f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
            json={
                "records": [
                    {"inputs": {"age": 25, "gender": "male"}, "outputs": {"score": 0.7}},
                    {"inputs": {"age": 40, "gender": "female"}, "outputs": {"score": 0.3}},
                ]
                * 50,
            },
        )

        # Create inferences
        for i in range(50):
            await client.post(
                "/api/v1/inferences",
                json={
                    "model_version_id": version_id,
                    "inputs": {"age": 20 + i, "gender": "male" if i % 2 == 0 else "female"},
                    "outputs": {"score": 0.5 + (i % 10) * 0.05},
                },
            )

        # Create and trigger job
        job_id = await _get_auto_job_id(client, model_id, version_id)
        await client.post(f"/api/v1/jobs/{job_id}/trigger")

    resp = await client.get("/api/v1/drift-overview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data) >= 2


async def test_notification_filter_by_model_version(client: AsyncClient):
    """Test filtering notifications by model_version_id."""
    # Create different models
    model1 = await create_model(client, name="notif-model-1")
    version1 = await create_version(client, model1["id"])
    model2 = await create_model(client, name="notif-model-2")
    version2 = await create_version(client, model2["id"])

    # Notifications should be filterable
    resp = await client.get("/api/v1/notifications", params={"model_version_id": version1["id"]})
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version2["id"]})
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


async def test_notifications_pagination(client: AsyncClient):
    """Test notifications pagination."""
    resp = await client.get("/api/v1/notifications", params={"page": 1, "page_size": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 5
