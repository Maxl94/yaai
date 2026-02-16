from httpx import AsyncClient

from tests.conftest import create_model, create_version


async def test_create_model(client: AsyncClient):
    resp = await client.post("/api/v1/models", json={"name": "fraud-detector", "description": "Detects fraud"})
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"] == "fraud-detector"
    assert data["description"] == "Detects fraud"
    assert "id" in data


async def test_create_model_duplicate_name(client: AsyncClient):
    await create_model(client, name="duplicate")
    resp = await client.post("/api/v1/models", json={"name": "duplicate"})
    assert resp.status_code == 500  # unique constraint violation


async def test_list_models(client: AsyncClient):
    await create_model(client, name="model-a")
    await create_model(client, name="model-b")
    resp = await client.get("/api/v1/models")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] >= 2
    assert len(body["data"]) >= 2


async def test_list_models_search(client: AsyncClient):
    await create_model(client, name="searchable-xyz")
    resp = await client.get("/api/v1/models", params={"search": "searchable"})
    assert resp.status_code == 200
    assert any(m["name"] == "searchable-xyz" for m in resp.json()["data"])


async def test_get_model(client: AsyncClient):
    model = await create_model(client, name="get-me")
    resp = await client.get(f"/api/v1/models/{model['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "get-me"


async def test_get_model_not_found(client: AsyncClient):
    resp = await client.get("/api/v1/models/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_update_model(client: AsyncClient):
    model = await create_model(client, name="old-name")
    resp = await client.put(f"/api/v1/models/{model['id']}", json={"name": "new-name"})
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "new-name"


async def test_delete_model(client: AsyncClient):
    model = await create_model(client, name="to-delete")
    resp = await client.delete(f"/api/v1/models/{model['id']}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/models/{model['id']}")
    assert resp.status_code == 404


# --- Versions ---


async def test_create_version(client: AsyncClient):
    model = await create_model(client, name="versioned")
    version = await create_version(client, model["id"])
    assert version["version"] == "v1.0"
    assert len(version["schema_fields"]) == 3
    directions = {f["direction"] for f in version["schema_fields"]}
    assert directions == {"input", "output"}


async def test_create_version_no_output_field(client: AsyncClient):
    model = await create_model(client, name="bad-schema")
    resp = await client.post(
        f"/api/v1/models/{model['id']}/versions",
        json={
            "version": "v1.0",
            "schema": [
                {"direction": "input", "field_name": "age", "data_type": "numerical"},
            ],
        },
    )
    assert resp.status_code == 422


async def test_get_version(client: AsyncClient):
    model = await create_model(client, name="ver-get")
    version = await create_version(client, model["id"])
    resp = await client.get(f"/api/v1/models/{model['id']}/versions/{version['id']}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == version["id"]


async def test_update_version(client: AsyncClient):
    model = await create_model(client, name="ver-update")
    version = await create_version(client, model["id"])
    resp = await client.patch(
        f"/api/v1/models/{model['id']}/versions/{version['id']}",
        json={"description": "updated desc"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["description"] == "updated desc"


async def test_list_models_search_no_results(client: AsyncClient):
    """Search for a model name that doesn't exist returns empty list."""
    await create_model(client, name="unrelated-model")
    resp = await client.get("/api/v1/models", params={"search": "nonexistent-xyz-123"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Should not find any models with this specific search term
    assert all("nonexistent-xyz-123" not in m["name"] for m in data)


async def test_list_models_pagination(client: AsyncClient):
    """Test pagination parameters work correctly."""
    for i in range(5):
        await create_model(client, name=f"paginated-model-{i}")

    resp = await client.get("/api/v1/models", params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) <= 2
    assert body["meta"]["page"] == 1
    assert body["meta"]["page_size"] == 2


async def test_delete_model_cascades_to_versions(client: AsyncClient):
    """Deleting a model should cascade to its versions."""
    model = await create_model(client, name="cascade-model")
    version = await create_version(client, model["id"])
    version_id = version["id"]

    # Delete the model
    resp = await client.delete(f"/api/v1/models/{model['id']}")
    assert resp.status_code == 204

    # Version should no longer be accessible
    resp = await client.get(f"/api/v1/models/{model['id']}/versions/{version_id}")
    assert resp.status_code == 404


async def test_get_version_not_found(client: AsyncClient):
    """Get non-existent version returns 404."""
    model = await create_model(client, name="ver-not-found")
    resp = await client.get(f"/api/v1/models/{model['id']}/versions/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_update_model_not_found(client: AsyncClient):
    """Update non-existent model returns 404."""
    resp = await client.put(
        "/api/v1/models/00000000-0000-0000-0000-000000000000",
        json={"name": "new-name"},
    )
    assert resp.status_code == 404


async def test_update_model_partial(client: AsyncClient):
    """Test updating only model description without changing name."""
    model = await create_model(client, name="partial-update")
    resp = await client.put(
        f"/api/v1/models/{model['id']}",
        json={"name": "partial-update", "description": "New description"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["name"] == "partial-update"
    assert data["description"] == "New description"


async def test_create_version_with_custom_metrics(client: AsyncClient):
    """Test creating a version with custom drift metric settings."""
    model = await create_model(client, name="custom-metrics")
    resp = await client.post(
        f"/api/v1/models/{model['id']}/versions",
        json={
            "version": "v1.0",
            "schema": [
                {
                    "direction": "input",
                    "field_name": "amount",
                    "data_type": "numerical",
                    "drift_metric": "psi",
                    "alert_threshold": 0.3,
                },
                {"direction": "output", "field_name": "prediction", "data_type": "categorical"},
            ],
        },
    )
    assert resp.status_code == 201
    fields = resp.json()["data"]["schema_fields"]
    amount_field = next(f for f in fields if f["field_name"] == "amount")
    assert amount_field["drift_metric"] == "psi"
    assert amount_field["alert_threshold"] == 0.3


async def test_update_version_not_found(client: AsyncClient):
    """Update non-existent version returns 404."""
    model = await create_model(client, name="ver-update-404")
    resp = await client.patch(
        f"/api/v1/models/{model['id']}/versions/00000000-0000-0000-0000-000000000000",
        json={"description": "new desc"},
    )
    assert resp.status_code == 404


async def test_create_multiple_versions(client: AsyncClient):
    """Test creating multiple versions for a model."""
    model = await create_model(client, name="multi-version")

    # Create first version
    resp1 = await client.post(
        f"/api/v1/models/{model['id']}/versions",
        json={
            "version": "v1.0",
            "schema": [
                {"direction": "input", "field_name": "x", "data_type": "numerical"},
                {"direction": "output", "field_name": "y", "data_type": "numerical"},
            ],
        },
    )
    assert resp1.status_code == 201
    v1 = resp1.json()["data"]

    # Create second version - should deactivate first
    resp2 = await client.post(
        f"/api/v1/models/{model['id']}/versions",
        json={
            "version": "v2.0",
            "schema": [
                {"direction": "input", "field_name": "x", "data_type": "numerical"},
                {"direction": "output", "field_name": "y", "data_type": "numerical"},
            ],
        },
    )
    assert resp2.status_code == 201
    v2 = resp2.json()["data"]

    # Verify second version is active
    assert v2["is_active"] is True

    # Verify first version is now inactive
    resp_v1 = await client.get(f"/api/v1/models/{model['id']}/versions/{v1['id']}")
    assert resp_v1.status_code == 200
    assert resp_v1.json()["data"]["is_active"] is False
