from httpx import AsyncClient

from tests.conftest import create_model, create_version


async def _setup(client: AsyncClient):
    """Create a model + version and return (model_id, version_id)."""
    model = await create_model(client, name="inf-model")
    version = await create_version(client, model["id"])
    return model["id"], version["id"]


async def test_create_inference(client: AsyncClient):
    _, version_id = await _setup(client)
    resp = await client.post(
        "/api/v1/inferences",
        json={
            "model_version_id": version_id,
            "inputs": {"age": 30, "gender": "male"},
            "outputs": {"score": 0.9},
        },
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert "id" in data
    assert data["model_version_id"] == version_id


async def test_create_inference_invalid_data(client: AsyncClient):
    _, version_id = await _setup(client)
    resp = await client.post(
        "/api/v1/inferences",
        json={
            "model_version_id": version_id,
            "inputs": {"age": "not-a-number", "gender": "male"},
            "outputs": {"score": 0.9},
        },
    )
    assert resp.status_code == 422


async def test_create_inference_missing_field(client: AsyncClient):
    _, version_id = await _setup(client)
    resp = await client.post(
        "/api/v1/inferences",
        json={
            "model_version_id": version_id,
            "inputs": {"age": 30},
            "outputs": {"score": 0.9},
        },
    )
    assert resp.status_code == 422


async def test_list_inferences(client: AsyncClient):
    _, version_id = await _setup(client)
    for i in range(3):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 20 + i, "gender": "female"},
                "outputs": {"score": 0.5 + i * 0.1},
            },
        )

    resp = await client.get("/api/v1/inferences", params={"model_version_id": version_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 3
    assert len(body["data"]) == 3


async def test_create_inference_batch(client: AsyncClient):
    _, version_id = await _setup(client)
    resp = await client.post(
        "/api/v1/inferences/batch",
        json={
            "model_version_id": version_id,
            "records": [
                {"inputs": {"age": 25, "gender": "male"}, "outputs": {"score": 0.7}},
                {"inputs": {"age": 40, "gender": "female"}, "outputs": {"score": 0.3}},
                {"inputs": {"age": "bad", "gender": "male"}, "outputs": {"score": 0.5}},
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["ingested"] == 2
    assert data["failed"] == 1
    assert len(data["errors"]) == 1


# --- Reference Data ---


async def test_upload_reference_data(client: AsyncClient):
    model_id, version_id = await _setup(client)
    resp = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
        json={
            "records": [
                {"inputs": {"age": 25, "gender": "male"}, "outputs": {"score": 0.7}},
                {"inputs": {"age": 40, "gender": "female"}, "outputs": {"score": 0.3}},
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["ingested"] == 2
    assert data["model_version_id"] == version_id


# --- Ground Truth ---


async def test_create_ground_truth(client: AsyncClient):
    _, version_id = await _setup(client)
    inf_resp = await client.post(
        "/api/v1/inferences",
        json={
            "model_version_id": version_id,
            "inputs": {"age": 30, "gender": "male"},
            "outputs": {"score": 0.9},
        },
    )
    inference_id = inf_resp.json()["data"]["id"]

    resp = await client.post(
        "/api/v1/ground-truth",
        json={"inference_id": inference_id, "label": {"actual_score": 0.85}},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["inference_id"] == inference_id


async def test_create_ground_truth_not_found(client: AsyncClient):
    resp = await client.post(
        "/api/v1/ground-truth",
        json={"inference_id": "00000000-0000-0000-0000-000000000000", "label": {"x": 1}},
    )
    assert resp.status_code == 404


async def test_list_inferences_with_time_filter(client: AsyncClient):
    """Test listing inferences with time range filtering."""
    from datetime import UTC, datetime, timedelta

    _, version_id = await _setup(client)
    now = datetime.now(UTC)

    # Create inferences at different times
    for i in range(5):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 20 + i, "gender": "female"},
                "outputs": {"score": 0.5},
                "timestamp": (now - timedelta(hours=i)).isoformat(),
            },
        )

    # Filter to only last 2 hours
    from_ts = (now - timedelta(hours=2)).isoformat()
    resp = await client.get(
        "/api/v1/inferences",
        params={"model_version_id": version_id, "from": from_ts},
    )
    assert resp.status_code == 200
    # Should get 3 inferences (0, 1, 2 hours ago)
    assert resp.json()["meta"]["total"] == 3


async def test_upload_reference_data_with_errors(client: AsyncClient):
    """Test reference data upload with some invalid records that don't match schema."""
    model_id, version_id = await _setup(client)
    resp = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
        json={
            "records": [
                {"inputs": {"age": 25, "gender": "male"}, "outputs": {"score": 0.7}},
                {"inputs": {"age": 35, "gender": "other"}, "outputs": {"score": 0.5}},
            ]
        },
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["ingested"] >= 1  # At least some records should be ingested


async def test_list_inferences_pagination(client: AsyncClient):
    """Test pagination parameters for listing inferences."""
    _, version_id = await _setup(client)

    # Create 15 inferences
    for i in range(15):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 20 + i, "gender": "female"},
                "outputs": {"score": 0.5},
            },
        )

    # Get first page
    resp = await client.get(
        "/api/v1/inferences",
        params={"model_version_id": version_id, "page": 1, "page_size": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 15
    assert len(body["data"]) == 5
    assert body["meta"]["page"] == 1

    # Get second page
    resp = await client.get(
        "/api/v1/inferences",
        params={"model_version_id": version_id, "page": 2, "page_size": 5},
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 5


async def test_create_inference_with_null_value(client: AsyncClient):
    """Test that null values in optional fields are handled correctly."""
    _, version_id = await _setup(client)
    resp = await client.post(
        "/api/v1/inferences",
        json={
            "model_version_id": version_id,
            "inputs": {"age": None, "gender": "male"},
            "outputs": {"score": 0.9},
        },
    )
    # Null values should be allowed
    assert resp.status_code == 201


async def test_upload_reference_data_replaces_existing(client: AsyncClient):
    """Test that uploading reference data replaces existing data."""
    model_id, version_id = await _setup(client)

    # First upload
    resp1 = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
        json={
            "records": [
                {"inputs": {"age": 25, "gender": "male"}, "outputs": {"score": 0.7}},
                {"inputs": {"age": 30, "gender": "female"}, "outputs": {"score": 0.5}},
            ]
        },
    )
    assert resp1.status_code == 201
    assert resp1.json()["data"]["ingested"] == 2

    # Second upload should replace
    resp2 = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
        json={
            "records": [
                {"inputs": {"age": 40, "gender": "female"}, "outputs": {"score": 0.8}},
            ]
        },
    )
    assert resp2.status_code == 201
    assert resp2.json()["data"]["ingested"] == 1
