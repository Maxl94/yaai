from httpx import AsyncClient

from tests.conftest import create_model, create_version


async def _setup(client: AsyncClient):
    """Create a model + version and return (model_id, version_id)."""
    model = await create_model(client, name="job-model")
    version = await create_version(client, model["id"])
    return model["id"], version["id"]


async def _get_auto_job(client: AsyncClient, model_id: str, version_id: str) -> dict:
    """Retrieve the auto-created job for a model version."""
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/jobs")
    assert resp.status_code == 200
    jobs = resp.json()["data"]
    assert len(jobs) == 1, f"Expected exactly 1 auto-created job, got {len(jobs)}"
    return jobs[0]


async def test_auto_created_job(client: AsyncClient):
    """Creating a version auto-creates exactly one job."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)
    assert job["is_active"] is True
    assert job["comparison_type"] == "vs_reference"
    assert job["window_size"] == "7d"
    assert "Daily Drift Check" in job["name"]


async def test_get_single_job(client: AsyncClient):
    """Test GET /jobs/{job_id} endpoint."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.get(f"/api/v1/jobs/{job['id']}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["id"] == job["id"]
    assert data["name"] == job["name"]


async def test_list_jobs(client: AsyncClient):
    """List jobs for a version returns the auto-created job."""
    model_id, version_id = await _setup(client)
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/jobs")
    assert resp.status_code == 200
    jobs = resp.json()["data"]
    assert len(jobs) == 1


async def test_list_all_jobs(client: AsyncClient):
    """Test listing all jobs across all models."""
    model_id, version_id = await _setup(client)

    resp = await client.get("/api/v1/jobs")
    assert resp.status_code == 200
    jobs = resp.json()["data"]
    assert len(jobs) >= 1
    assert "meta" in resp.json()


async def test_update_job(client: AsyncClient):
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"name": "Updated name", "is_active": True},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Updated name"
    assert resp.json()["data"]["is_active"] is True


async def test_update_job_comparison_type(client: AsyncClient):
    """Test updating a job's comparison_type."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)
    assert job["comparison_type"] == "vs_reference"

    resp = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"comparison_type": "rolling_window"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["comparison_type"] == "rolling_window"


async def test_update_job_window_size(client: AsyncClient):
    """Test updating a job's window_size."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"window_size": "30d"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["window_size"] == "30d"


async def test_update_job_schedule(client: AsyncClient):
    """Test updating a job's schedule."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"schedule": "0 0 * * *"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["schedule"] == "0 0 * * *"


async def test_update_job_min_samples(client: AsyncClient):
    """Test updating a job's min_samples."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"min_samples": 500},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["min_samples"] == 500


async def test_update_job_deactivate(client: AsyncClient):
    """Test deactivating a job."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"is_active": False},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is False


async def test_update_job_not_found(client: AsyncClient):
    """Updating a non-existent job returns 404."""
    resp = await client.patch(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000",
        json={"name": "new name"},
    )
    assert resp.status_code == 404


async def test_list_job_runs_empty(client: AsyncClient):
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.get(f"/api/v1/jobs/{job['id']}/runs")
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 0
    assert resp.json()["data"] == []


async def test_backfill_job(client: AsyncClient):
    """Test backfill endpoint returns expected response structure."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.post(f"/api/v1/jobs/{job['id']}/backfill")
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert "runs_created" in data
    assert isinstance(data["runs_created"], int)


async def test_trigger_job_no_reference(client: AsyncClient):
    """Test triggering a job without reference data fails gracefully."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.post(f"/api/v1/jobs/{job['id']}/trigger")
    assert resp.status_code == 201
    run = resp.json()["data"]
    assert run["status"] == "failed"


async def test_trigger_job_not_found(client: AsyncClient):
    """Test triggering non-existent job returns 404."""
    resp = await client.post("/api/v1/jobs/00000000-0000-0000-0000-000000000000/trigger")
    assert resp.status_code == 404


async def test_list_job_runs_pagination(client: AsyncClient):
    """Test job runs list pagination."""
    model_id, version_id = await _setup(client)
    job = await _get_auto_job(client, model_id, version_id)

    resp = await client.get(
        f"/api/v1/jobs/{job['id']}/runs",
        params={"page": 1, "page_size": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "meta" in body
    assert body["meta"]["page"] == 1


async def test_list_all_jobs_pagination(client: AsyncClient):
    """Test global jobs list pagination."""
    # Create multiple models to get multiple jobs
    for i in range(3):
        model = await create_model(client, name=f"paginate-model-{i}")
        await create_version(client, model["id"])

    resp = await client.get("/api/v1/jobs", params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) <= 2
    assert body["meta"]["page"] == 1


# --- Notifications ---


async def test_list_notifications_empty(client: AsyncClient):
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


async def test_mark_all_notifications_read(client: AsyncClient):
    resp = await client.post("/api/v1/notifications/mark-all-read")
    assert resp.status_code == 200
    assert resp.json()["data"]["marked_read"] == 0


async def test_mark_notification_read_not_found(client: AsyncClient):
    """Test marking non-existent notification as read returns 404."""
    resp = await client.patch("/api/v1/notifications/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_list_notifications_with_filters(client: AsyncClient):
    """Test listing notifications with read status filter."""
    resp = await client.get("/api/v1/notifications", params={"is_read": "false"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


# --- Drift Results ---


async def test_list_drift_results_empty(client: AsyncClient):
    model_id, version_id = await _setup(client)
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/drift-results")
    assert resp.status_code == 200
    assert resp.json()["meta"]["total"] == 0
