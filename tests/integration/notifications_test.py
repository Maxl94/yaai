"""Comprehensive tests for the notifications API.

Covers notification lifecycle: creation via drift detection, listing with
filters, mark-read (single and bulk), pagination, response schema, and
edge cases.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from tests.conftest import create_model, create_version

# Helpers


async def _setup_drifted(
    client: AsyncClient,
    model_name: str = "notif-model",
) -> tuple[str, str, str]:
    """Create model + version with shifted data, trigger drift, return (model_id, version_id, job_id)."""
    model = await create_model(client, name=model_name)
    version = await create_version(client, model["id"])
    model_id, version_id = model["id"], version["id"]

    # Reference: tight age distribution
    ref_records = [
        {"inputs": {"age": 25 + i, "gender": "male" if i % 2 == 0 else "female"}, "outputs": {"score": 0.5}}
        for i in range(100)
    ]
    resp = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
        json={"records": ref_records},
    )
    assert resp.status_code == 201

    # Inference: heavily shifted age distribution → guaranteed PSI drift
    now = datetime.now(UTC)
    for i in range(100):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 200 + i, "gender": "male" if i % 2 == 0 else "female"},
                "outputs": {"score": 0.5},
                "timestamp": (now - timedelta(minutes=i)).isoformat(),
            },
        )

    # Get auto-created job and trigger
    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/jobs")
    assert resp.status_code == 200
    job_id = resp.json()["data"][0]["id"]

    resp = await client.post(f"/api/v1/jobs/{job_id}/trigger")
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "completed"

    return model_id, version_id, job_id


async def _setup_no_drift(
    client: AsyncClient,
    model_name: str = "no-drift-model",
) -> tuple[str, str, str]:
    """Create model + version with identical data, trigger job (no drift)."""
    model = await create_model(client, name=model_name)
    version = await create_version(client, model["id"])
    model_id, version_id = model["id"], version["id"]

    records = [
        {"inputs": {"age": 25 + i, "gender": "male" if i % 2 == 0 else "female"}, "outputs": {"score": 0.5}}
        for i in range(100)
    ]
    resp = await client.post(
        f"/api/v1/models/{model_id}/versions/{version_id}/reference-data",
        json={"records": records},
    )
    assert resp.status_code == 201

    now = datetime.now(UTC)
    for i in range(100):
        await client.post(
            "/api/v1/inferences",
            json={
                "model_version_id": version_id,
                "inputs": {"age": 25 + i, "gender": "male" if i % 2 == 0 else "female"},
                "outputs": {"score": 0.5},
                "timestamp": (now - timedelta(minutes=i)).isoformat(),
            },
        )

    resp = await client.get(f"/api/v1/models/{model_id}/versions/{version_id}/jobs")
    job_id = resp.json()["data"][0]["id"]
    resp = await client.post(f"/api/v1/jobs/{job_id}/trigger")
    assert resp.status_code == 201

    return model_id, version_id, job_id


# Notification creation


async def test_drift_creates_notifications(client: AsyncClient):
    """Drift detection should create at least one notification."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    assert resp.status_code == 200
    notifications = resp.json()["data"]
    assert len(notifications) > 0


async def test_no_drift_creates_no_notifications(client: AsyncClient):
    """Identical distributions should not produce any notifications."""
    _model_id, version_id, _job_id = await _setup_no_drift(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    assert resp.status_code == 200
    notifications = resp.json()["data"]
    assert len(notifications) == 0


# Notification response schema


async def test_notification_response_schema(client: AsyncClient):
    """Notification response should contain all required fields with correct types."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    notifications = resp.json()["data"]
    assert len(notifications) > 0

    n = notifications[0]
    assert "id" in n
    assert "model_version_id" in n
    assert "severity" in n
    assert "message" in n
    assert "is_read" in n
    assert "created_at" in n
    assert "drift_result_id" in n

    # Verify types
    assert isinstance(n["id"], str)
    assert isinstance(n["message"], str)
    assert isinstance(n["is_read"], bool)
    assert n["severity"] in ("info", "warning", "critical")
    assert n["model_version_id"] == version_id


async def test_notification_message_contains_drift_info(client: AsyncClient):
    """Notification message should contain field name, metric name, and values."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    notifications = resp.json()["data"]

    for n in notifications:
        assert "Drift detected" in n["message"]
        assert "threshold" in n["message"]


async def test_notification_severity_values(client: AsyncClient):
    """All notification severities should be valid enum values."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    notifications = resp.json()["data"]
    for n in notifications:
        assert n["severity"] in ("info", "warning", "critical")


async def test_notifications_created_as_unread(client: AsyncClient):
    """New notifications should default to is_read=False."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    notifications = resp.json()["data"]
    assert all(n["is_read"] is False for n in notifications)


# Mark single notification read


async def test_mark_notification_read(client: AsyncClient):
    """PATCH /notifications/{id} should set is_read to True."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    notifications = resp.json()["data"]
    notif_id = notifications[0]["id"]

    # Mark read
    resp = await client.patch(f"/api/v1/notifications/{notif_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_read"] is True
    assert resp.json()["data"]["id"] == notif_id


async def test_mark_notification_read_is_idempotent(client: AsyncClient):
    """Marking an already-read notification should succeed (idempotent)."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    notif_id = resp.json()["data"][0]["id"]

    # Mark read twice
    resp = await client.patch(f"/api/v1/notifications/{notif_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_read"] is True

    resp = await client.patch(f"/api/v1/notifications/{notif_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["is_read"] is True


async def test_mark_notification_read_not_found(client: AsyncClient):
    """Marking a non-existent notification should return 404."""
    resp = await client.patch("/api/v1/notifications/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_mark_read_persists_in_list(client: AsyncClient):
    """After marking read, listing should reflect the change."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    notif_id = resp.json()["data"][0]["id"]

    # Mark read
    await client.patch(f"/api/v1/notifications/{notif_id}")

    # Re-list and verify
    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    notification = next(n for n in resp.json()["data"] if n["id"] == notif_id)
    assert notification["is_read"] is True


# Mark all read


async def test_mark_all_read_with_notifications(client: AsyncClient):
    """Mark-all-read should update all unread notifications and return count."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    # Verify there are unread notifications
    resp = await client.get("/api/v1/notifications", params={"is_read": "false"})
    unread_count = resp.json()["meta"]["total"]
    assert unread_count > 0

    # Mark all read
    resp = await client.post("/api/v1/notifications/mark-all-read")
    assert resp.status_code == 200
    assert resp.json()["data"]["marked_read"] == unread_count

    # Verify all are now read
    resp = await client.get("/api/v1/notifications", params={"is_read": "false"})
    assert resp.json()["meta"]["total"] == 0


async def test_mark_all_read_empty(client: AsyncClient):
    """Mark-all-read with no notifications should return 0."""
    resp = await client.post("/api/v1/notifications/mark-all-read")
    assert resp.status_code == 200
    assert resp.json()["data"]["marked_read"] == 0


async def test_mark_all_read_idempotent(client: AsyncClient):
    """Calling mark-all-read twice should return 0 on second call."""
    _model_id, _version_id, _job_id = await _setup_drifted(client)

    resp = await client.post("/api/v1/notifications/mark-all-read")
    assert resp.status_code == 200
    first_count = resp.json()["data"]["marked_read"]
    assert first_count > 0

    resp = await client.post("/api/v1/notifications/mark-all-read")
    assert resp.status_code == 200
    assert resp.json()["data"]["marked_read"] == 0


# Filtering


async def test_filter_by_is_read_false(client: AsyncClient):
    """Filter is_read=false should return only unread notifications."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    resp = await client.get(
        "/api/v1/notifications",
        params={"model_version_id": version_id, "is_read": "false"},
    )
    assert resp.status_code == 200
    notifications = resp.json()["data"]
    assert len(notifications) > 0
    assert all(n["is_read"] is False for n in notifications)


async def test_filter_by_is_read_true(client: AsyncClient):
    """Filter is_read=true should return only read notifications."""
    _model_id, version_id, _job_id = await _setup_drifted(client)

    # Mark one notification as read
    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    notif_id = resp.json()["data"][0]["id"]
    await client.patch(f"/api/v1/notifications/{notif_id}")

    # Filter for read only
    resp = await client.get(
        "/api/v1/notifications",
        params={"model_version_id": version_id, "is_read": "true"},
    )
    assert resp.status_code == 200
    notifications = resp.json()["data"]
    assert len(notifications) == 1
    assert notifications[0]["is_read"] is True
    assert notifications[0]["id"] == notif_id


async def test_filter_by_model_version_id(client: AsyncClient):
    """Notifications should be filtered to the correct model version."""
    _m1, v1, _j1 = await _setup_drifted(client, model_name="notif-filter-1")
    _m2, v2, _j2 = await _setup_no_drift(client, model_name="notif-filter-2")

    resp1 = await client.get("/api/v1/notifications", params={"model_version_id": v1})
    resp2 = await client.get("/api/v1/notifications", params={"model_version_id": v2})

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    # Drifted model should have notifications, non-drifted should not
    assert len(resp1.json()["data"]) > 0
    assert len(resp2.json()["data"]) == 0


async def test_filter_combined_model_version_and_is_read(client: AsyncClient):
    """Combining model_version_id and is_read filters should work."""
    _m, version_id, _j = await _setup_drifted(client, model_name="combined-filter")

    # Mark first notification as read
    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    total = len(resp.json()["data"])
    notif_id = resp.json()["data"][0]["id"]
    await client.patch(f"/api/v1/notifications/{notif_id}")

    # Filter: model_version_id + is_read=false
    resp = await client.get(
        "/api/v1/notifications",
        params={"model_version_id": version_id, "is_read": "false"},
    )
    assert len(resp.json()["data"]) == total - 1

    # Filter: model_version_id + is_read=true
    resp = await client.get(
        "/api/v1/notifications",
        params={"model_version_id": version_id, "is_read": "true"},
    )
    assert len(resp.json()["data"]) == 1


# Pagination


async def test_notifications_pagination_meta(client: AsyncClient):
    """Pagination meta should contain total, page, and page_size."""
    _m, _v, _j = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"page": 1, "page_size": 1})
    assert resp.status_code == 200
    meta = resp.json()["meta"]
    assert meta["page"] == 1
    assert meta["page_size"] == 1
    assert meta["total"] > 0
    assert len(resp.json()["data"]) <= 1


async def test_notifications_pagination_limits_results(client: AsyncClient):
    """Page size should limit the number of returned notifications."""
    _m, _v, _j = await _setup_drifted(client)

    resp_all = await client.get("/api/v1/notifications", params={"page_size": 100})
    total = resp_all.json()["meta"]["total"]

    if total > 1:
        resp_paged = await client.get("/api/v1/notifications", params={"page": 1, "page_size": 1})
        assert len(resp_paged.json()["data"]) == 1
        assert resp_paged.json()["meta"]["total"] == total


async def test_notifications_page_beyond_results(client: AsyncClient):
    """Requesting a page beyond available data should return empty list."""
    resp = await client.get("/api/v1/notifications", params={"page": 999, "page_size": 20})
    assert resp.status_code == 200
    assert resp.json()["data"] == []


# Ordering


async def test_notifications_ordered_by_created_at_desc(client: AsyncClient):
    """Notifications should be ordered by created_at descending (newest first)."""
    _m, _v, _j = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications")
    notifications = resp.json()["data"]
    if len(notifications) > 1:
        dates = [n["created_at"] for n in notifications]
        assert dates == sorted(dates, reverse=True)


# Cross-model isolation


async def test_notifications_isolated_between_models(client: AsyncClient):
    """Notifications for one model should not appear in another model's list."""
    _m1, v1, _j1 = await _setup_drifted(client, model_name="iso-model-1")
    _m2, v2, _j2 = await _setup_drifted(client, model_name="iso-model-2")

    resp1 = await client.get("/api/v1/notifications", params={"model_version_id": v1})
    resp2 = await client.get("/api/v1/notifications", params={"model_version_id": v2})

    notifs1 = resp1.json()["data"]
    notifs2 = resp2.json()["data"]

    # Both should have notifications
    assert len(notifs1) > 0
    assert len(notifs2) > 0

    # All v1 notifications should reference v1
    assert all(n["model_version_id"] == v1 for n in notifs1)
    # All v2 notifications should reference v2
    assert all(n["model_version_id"] == v2 for n in notifs2)

    # IDs should not overlap
    ids1 = {n["id"] for n in notifs1}
    ids2 = {n["id"] for n in notifs2}
    assert ids1.isdisjoint(ids2)


# Edge cases


async def test_list_notifications_no_results(client: AsyncClient):
    """Empty database should return empty list with correct structure."""
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200
    assert resp.json()["data"] == []
    assert resp.json()["meta"]["total"] == 0


async def test_mark_read_does_not_delete(client: AsyncClient):
    """Marking as read should not remove the notification from results."""
    _m, version_id, _j = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    total_before = resp.json()["meta"]["total"]

    # Mark all read
    await client.post("/api/v1/notifications/mark-all-read")

    # Total count should remain the same
    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    total_after = resp.json()["meta"]["total"]
    assert total_after == total_before


async def test_multiple_triggers_create_more_notifications(client: AsyncClient):
    """Triggering drift detection multiple times should create additional notifications."""
    model_id, version_id, job_id = await _setup_drifted(client)

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    count_after_first = resp.json()["meta"]["total"]
    assert count_after_first > 0

    # Trigger again
    resp = await client.post(f"/api/v1/jobs/{job_id}/trigger")
    assert resp.status_code == 201

    resp = await client.get("/api/v1/notifications", params={"model_version_id": version_id})
    count_after_second = resp.json()["meta"]["total"]
    assert count_after_second > count_after_first
