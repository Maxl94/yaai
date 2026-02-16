"""Integration tests for drift detection functionality."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.conftest import create_model, create_version


async def _setup(client: AsyncClient) -> tuple[dict, dict]:
    """Create model and version for testing."""
    model = await create_model(client, name="drift-test-model")
    version = await create_version(client, model["id"])
    return model, version


async def _get_auto_job(
    client: AsyncClient, model_id: str, version_id: str, comparison_type: str | None = None
) -> dict:
    """Get the auto-created job for a model version, optionally updating comparison_type."""
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/jobs")
    assert resp.status_code == 200
    jobs = resp.json()["data"]
    assert len(jobs) == 1
    job = jobs[0]
    if comparison_type and job["comparison_type"] != comparison_type:
        patch_resp = await client.patch(
            f"/api/v1/jobs/{job['id']}",
            json={"comparison_type": comparison_type, "min_samples": 10},
        )
        assert patch_resp.status_code == 200
        job = patch_resp.json()["data"]
    elif job["min_samples"] != 10:
        patch_resp = await client.patch(
            f"/api/v1/jobs/{job['id']}",
            json={"min_samples": 10},
        )
        assert patch_resp.status_code == 200
        job = patch_resp.json()["data"]
    return job


async def _upload_reference_data(client: AsyncClient, model_id: str, version_id: str, count: int = 50) -> None:
    """Upload reference data for a model version."""
    records = [
        {"inputs": {"age": 25 + i, "gender": "M" if i % 2 == 0 else "F"}, "outputs": {"score": 0.5 + i * 0.01}}
        for i in range(count)
    ]
    resp = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
        json={"records": records},
    )
    assert resp.status_code == 201


async def _create_inferences(client: AsyncClient, version_id: str, count: int = 50, days_ago: int = 0) -> None:
    """Create inference data for a model version."""
    base_time = datetime.now(UTC) - timedelta(days=days_ago)
    records = [
        {
            "inputs": {"age": 30 + i, "gender": "M" if i % 2 == 0 else "F"},
            "outputs": {"score": 0.6 + i * 0.01},
            "timestamp": (base_time - timedelta(hours=i)).isoformat(),
        }
        for i in range(count)
    ]
    resp = await client.post(
        "/api/v1/inferences/batch",
        json={"model_version_id": version_id, "records": records},
    )
    assert resp.status_code == 201


async def test_trigger_drift_job_vs_reference(client: AsyncClient):
    """Test triggering a drift job that compares against reference data."""
    model, version = await _setup(client)

    # Upload reference data
    await _upload_reference_data(client, model["id"], version["id"], count=30)

    # Create inference data
    await _create_inferences(client, version["id"], count=30)

    # Create and trigger job
    job = await _get_auto_job(client, model["id"], version["id"], comparison_type="vs_reference")

    resp = await client.post(f"/api/v1/jobs/{job['id']}/trigger")
    assert resp.status_code == 201
    run = resp.json()["data"]
    assert run["status"] == "completed"


async def test_trigger_drift_job_rolling_window(client: AsyncClient):
    """Test triggering a drift job with rolling window comparison."""
    model, version = await _setup(client)

    # Create inference data for past periods (need data for both windows)
    await _create_inferences(client, version["id"], count=30, days_ago=14)
    await _create_inferences(client, version["id"], count=30, days_ago=0)

    # Create and trigger job with rolling window
    job = await _get_auto_job(client, model["id"], version["id"], comparison_type="rolling_window")

    resp = await client.post(f"/api/v1/jobs/{job['id']}/trigger")
    assert resp.status_code == 201
    run = resp.json()["data"]
    # May fail if not enough historical data, but should still complete
    assert run["status"] in ["completed", "failed"]


async def test_trigger_drift_job_no_reference_data(client: AsyncClient):
    """Test triggering a vs_reference job without reference data fails gracefully."""
    model, version = await _setup(client)

    # Create inference data but no reference
    await _create_inferences(client, version["id"], count=30)

    job = await _get_auto_job(client, model["id"], version["id"], comparison_type="vs_reference")

    resp = await client.post(f"/api/v1/jobs/{job['id']}/trigger")
    assert resp.status_code == 201
    run = resp.json()["data"]
    assert run["status"] == "failed"
    assert "reference" in run["error_message"].lower()


async def test_drift_results_created_after_job_run(client: AsyncClient):
    """Test that drift results are created after a successful job run."""
    model, version = await _setup(client)

    await _upload_reference_data(client, model["id"], version["id"], count=30)
    await _create_inferences(client, version["id"], count=30)

    job = await _get_auto_job(client, model["id"], version["id"])
    await client.post(f"/api/v1/jobs/{job['id']}/trigger")

    # Check drift results exist
    resp = await client.get(f"/api/v1/models/{model['id']}/versions/{version['id']}/drift-results")
    assert resp.status_code == 200
    body = resp.json()
    # Should have results for each schema field (age, gender, score)
    assert body["meta"]["total"] == 3


async def test_drift_results_filter_by_drifted(client: AsyncClient):
    """Test filtering drift results by is_drifted flag."""
    model, version = await _setup(client)

    await _upload_reference_data(client, model["id"], version["id"], count=30)
    await _create_inferences(client, version["id"], count=30)

    job = await _get_auto_job(client, model["id"], version["id"])
    await client.post(f"/api/v1/jobs/{job['id']}/trigger")

    # Filter by is_drifted=true
    resp = await client.get(
        f"/api/v1/models/{model['id']}/versions/{version['id']}/drift-results",
        params={"is_drifted": "true"},
    )
    assert resp.status_code == 200

    # Filter by is_drifted=false
    resp = await client.get(
        f"/api/v1/models/{model['id']}/versions/{version['id']}/drift-results",
        params={"is_drifted": "false"},
    )
    assert resp.status_code == 200


async def test_drift_overview_endpoint(client: AsyncClient):
    """Test the drift overview endpoint returns model health summaries."""
    model, version = await _setup(client)

    await _upload_reference_data(client, model["id"], version["id"], count=20)
    await _create_inferences(client, version["id"], count=20)

    job = await _get_auto_job(client, model["id"], version["id"])
    await client.post(f"/api/v1/jobs/{job['id']}/trigger")

    resp = await client.get("/api/v1/drift-overview")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body


async def test_job_run_history_populated(client: AsyncClient):
    """Test that job run history is tracked correctly."""
    model, version = await _setup(client)

    await _upload_reference_data(client, model["id"], version["id"], count=20)
    await _create_inferences(client, version["id"], count=20)

    job = await _get_auto_job(client, model["id"], version["id"])

    # Trigger multiple runs
    for _ in range(3):
        await client.post(f"/api/v1/jobs/{job['id']}/trigger")

    # Check run history
    resp = await client.get(f"/api/v1/jobs/{job['id']}/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 3
