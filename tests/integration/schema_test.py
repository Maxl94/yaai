from httpx import AsyncClient

from tests.conftest import create_model, create_version


async def test_infer_schema_basic(client: AsyncClient):
    """Test inferring schema from a sample with mixed types."""
    resp = await client.post(
        "/api/v1/schema/infer",
        json={
            "sample": {
                "inputs": {
                    "age": 25,
                    "income": 50000.0,
                    "country": "DE",
                    "is_premium": True,
                },
                "outputs": {
                    "score": 0.85,
                    "category": "approved",
                },
            }
        },
    )
    assert resp.status_code == 200
    fields = resp.json()["data"]["schema_fields"]

    # Check we got all 6 fields
    assert len(fields) == 6

    # Build a lookup by (direction, field_name)
    field_map = {(f["direction"], f["field_name"]): f for f in fields}

    # Numerical inputs
    assert field_map[("input", "age")]["data_type"] == "numerical"
    assert field_map[("input", "income")]["data_type"] == "numerical"

    # Categorical inputs
    assert field_map[("input", "country")]["data_type"] == "categorical"
    assert field_map[("input", "is_premium")]["data_type"] == "categorical"  # bool -> categorical

    # Outputs
    assert field_map[("output", "score")]["data_type"] == "numerical"
    assert field_map[("output", "category")]["data_type"] == "categorical"


async def test_infer_schema_empty_inputs(client: AsyncClient):
    """Test inferring schema with only outputs."""
    resp = await client.post(
        "/api/v1/schema/infer",
        json={
            "sample": {
                "inputs": {},
                "outputs": {"prediction": 0.5},
            }
        },
    )
    assert resp.status_code == 200
    fields = resp.json()["data"]["schema_fields"]
    assert len(fields) == 1
    assert fields[0]["direction"] == "output"
    assert fields[0]["field_name"] == "prediction"


async def test_infer_schema_missing_outputs_key(client: AsyncClient):
    """Test inferring schema when outputs key is missing."""
    resp = await client.post(
        "/api/v1/schema/infer",
        json={
            "sample": {
                "inputs": {"feature": 1.0},
            }
        },
    )
    assert resp.status_code == 200
    fields = resp.json()["data"]["schema_fields"]
    assert len(fields) == 1
    assert fields[0]["direction"] == "input"


async def _setup(client: AsyncClient):
    model = await create_model(client, name="schema-model")
    version = await create_version(client, model["id"])
    return model["id"], version["id"]


async def test_overwrite_schema(client: AsyncClient):
    model_id, version_id = await _setup(client)
    resp = await client.put(
        f"/api/v1/models/{model_id}/versions/{version_id}/schema",
        json=[
            {"field_name": "temperature", "direction": "input", "data_type": "numerical"},
            {"field_name": "risk", "direction": "output", "data_type": "numerical"},
        ],
    )
    assert resp.status_code == 200

    # Re-fetch to get the updated schema (response may have stale eager-loaded fields)
    version_resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}")
    assert version_resp.status_code == 200
    fields = version_resp.json()["data"]["schema_fields"]
    field_names = {f["field_name"] for f in fields}
    assert "temperature" in field_names
    assert "risk" in field_names


async def test_overwrite_schema_requires_output(client: AsyncClient):
    model_id, version_id = await _setup(client)
    resp = await client.put(
        f"/api/v1/models/{model_id}/versions/{version_id}/schema",
        json=[
            {"field_name": "temperature", "direction": "input", "data_type": "numerical"},
        ],
    )
    assert resp.status_code == 422


async def test_update_field_threshold(client: AsyncClient):
    model_id, version_id = await _setup(client)
    version_resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}")
    field_id = version_resp.json()["data"]["schema_fields"][0]["id"]

    resp = await client.patch(
        f"/api/v1/models/{model_id}/versions/{version_id}/fields/{field_id}/threshold",
        json={"alert_threshold": 0.25},
    )
    assert resp.status_code == 200

    updated = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}")
    field = next(f for f in updated.json()["data"]["schema_fields"] if f["id"] == field_id)
    assert field["alert_threshold"] == 0.25


async def test_update_field_threshold_null(client: AsyncClient):
    model_id, version_id = await _setup(client)
    version_resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}")
    field_id = version_resp.json()["data"]["schema_fields"][0]["id"]

    # Set, then clear
    await client.patch(
        f"/api/v1/models/{model_id}/versions/{version_id}/fields/{field_id}/threshold",
        json={"alert_threshold": 0.25},
    )
    resp = await client.patch(
        f"/api/v1/models/{model_id}/versions/{version_id}/fields/{field_id}/threshold",
        json={"alert_threshold": None},
    )
    assert resp.status_code == 200


async def test_overwrite_schema_rejected_when_drift_results_exist(client: AsyncClient):
    """Schema overwrite should be rejected (409) if drift results already exist."""
    model_id, version_id = await _setup(client)

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

    # Get and trigger the auto-created job to generate drift results
    jobs_resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/jobs")
    job_id = jobs_resp.json()["data"][0]["id"]
    await client.post(f"/api/v1/jobs/{job_id}/trigger")

    # Attempt to overwrite schema - should fail with 409
    resp = await client.put(
        f"/api/v1/models/{model_id}/versions/{version_id}/schema",
        json=[
            {"field_name": "new_field", "direction": "input", "data_type": "numerical"},
            {"field_name": "new_output", "direction": "output", "data_type": "numerical"},
        ],
    )
    assert resp.status_code == 409
    assert "locked" in resp.json()["detail"].lower()


async def test_overwrite_schema_duplicate_field(client: AsyncClient):
    """Schema overwrite should reject duplicate field names (same name + direction)."""
    model_id, version_id = await _setup(client)
    resp = await client.put(
        f"/api/v1/models/{model_id}/versions/{version_id}/schema",
        json=[
            {"field_name": "age", "direction": "input", "data_type": "numerical"},
            {"field_name": "age", "direction": "input", "data_type": "categorical"},
            {"field_name": "score", "direction": "output", "data_type": "numerical"},
        ],
    )
    assert resp.status_code == 422
    assert "duplicate" in resp.json()["detail"].lower()


# -- Batch infer tests --


async def test_infer_schema_batch_merges_samples(client: AsyncClient):
    """Batch infer should merge fields from multiple samples."""
    resp = await client.post(
        "/api/v1/schema/infer/batch",
        json={
            "samples": [
                {"inputs": {"age": 25}, "outputs": {"score": 0.5}},
                {"inputs": {"age": 30, "name": "Alice"}, "outputs": {"score": 0.9}},
            ]
        },
    )
    assert resp.status_code == 200
    fields = resp.json()["data"]["schema_fields"]
    field_map = {(f["direction"], f["field_name"]): f for f in fields}

    # age and score from both samples, name only from second
    assert ("input", "age") in field_map
    assert ("input", "name") in field_map
    assert ("output", "score") in field_map
    assert field_map[("input", "age")]["data_type"] == "numerical"
    assert field_map[("input", "name")]["data_type"] == "categorical"


async def test_infer_schema_batch_type_conflict_resolves_to_categorical(client: AsyncClient):
    """When a field has conflicting types across samples, it should default to categorical."""
    resp = await client.post(
        "/api/v1/schema/infer/batch",
        json={
            "samples": [
                {"inputs": {"feature": 1.0}, "outputs": {"pred": 0.5}},
                {"inputs": {"feature": "high"}, "outputs": {"pred": 0.9}},
            ]
        },
    )
    assert resp.status_code == 200
    fields = resp.json()["data"]["schema_fields"]
    field_map = {(f["direction"], f["field_name"]): f for f in fields}

    # feature is numerical in sample 1, categorical in sample 2 -> categorical
    assert field_map[("input", "feature")]["data_type"] == "categorical"


# -- General validate tests --


async def test_validate_schema_valid(client: AsyncClient):
    """Validate a single record that matches the schema."""
    resp = await client.post(
        "/api/v1/schema/validate",
        json={
            "schema": [
                {"direction": "input", "field_name": "age", "data_type": "numerical"},
                {"direction": "output", "field_name": "score", "data_type": "numerical"},
            ],
            "inputs": {"age": 25},
            "outputs": {"score": 0.85},
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is True
    assert all(f["status"] == "ok" for f in data["fields"])


async def test_validate_schema_missing_field(client: AsyncClient):
    """Validation should report missing fields."""
    resp = await client.post(
        "/api/v1/schema/validate",
        json={
            "schema": [
                {"direction": "input", "field_name": "age", "data_type": "numerical"},
                {"direction": "input", "field_name": "income", "data_type": "numerical"},
                {"direction": "output", "field_name": "score", "data_type": "numerical"},
            ],
            "inputs": {"age": 25},
            "outputs": {"score": 0.85},
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    missing = [f for f in data["fields"] if f["status"] == "missing"]
    assert len(missing) == 1
    assert missing[0]["field_name"] == "income"


async def test_validate_schema_wrong_type(client: AsyncClient):
    """Validation should report type mismatches."""
    resp = await client.post(
        "/api/v1/schema/validate",
        json={
            "schema": [
                {"direction": "input", "field_name": "age", "data_type": "numerical"},
                {"direction": "output", "field_name": "score", "data_type": "numerical"},
            ],
            "inputs": {"age": "twenty-five"},
            "outputs": {"score": 0.85},
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    errors = [f for f in data["fields"] if f["status"] == "error"]
    assert len(errors) == 1
    assert errors[0]["field_name"] == "age"


async def test_validate_schema_batch_mixed(client: AsyncClient):
    """Batch validation returns summary with only invalid records."""
    resp = await client.post(
        "/api/v1/schema/validate/batch",
        json={
            "schema": [
                {"direction": "input", "field_name": "age", "data_type": "numerical"},
                {"direction": "output", "field_name": "score", "data_type": "numerical"},
            ],
            "records": [
                {"inputs": {"age": 25}, "outputs": {"score": 0.85}},
                {"inputs": {"age": "bad"}, "outputs": {"score": 0.5}},
                {"inputs": {"age": 30}, "outputs": {"score": 0.9}},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 3
    assert data["valid"] == 2
    assert data["invalid"] == 1
    assert len(data["records"]) == 1
    assert data["records"][0]["index"] == 1


# -- Model version validate tests --


async def test_validate_model_version_valid(client: AsyncClient):
    """Validate a single record against a model version's schema."""
    model_id, version_id = await _setup(client)
    resp = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/schema/validate",
        json={
            "inputs": {"age": 25, "gender": "male"},
            "outputs": {"score": 0.85},
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is True


async def test_validate_model_version_invalid(client: AsyncClient):
    """Validate an invalid record against a model version's schema."""
    model_id, version_id = await _setup(client)
    resp = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/schema/validate",
        json={
            "inputs": {"age": "not-a-number", "gender": "male"},
            "outputs": {"score": 0.85},
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["valid"] is False
    errors = [f for f in data["fields"] if f["status"] == "error"]
    assert any(f["field_name"] == "age" for f in errors)


async def test_validate_model_version_batch(client: AsyncClient):
    """Batch validate against a model version's schema."""
    model_id, version_id = await _setup(client)
    resp = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/schema/validate/batch",
        json={
            "records": [
                {"inputs": {"age": 25, "gender": "male"}, "outputs": {"score": 0.85}},
                {"inputs": {"gender": "female"}, "outputs": {"score": 0.5}},
                {"inputs": {"age": 30, "gender": "male"}, "outputs": {"score": 0.9}},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 3
    assert data["valid"] == 2
    assert data["invalid"] == 1
    assert data["records"][0]["index"] == 1
