"""Unit tests for the YaaiClient SDK."""

import uuid

import httpx
import pytest

from yaai.client import YaaiClient


@pytest.fixture
def mock_transport():
    """Create a mock transport that returns predefined responses."""
    return MockTransport()


class MockTransport(httpx.AsyncBaseTransport):
    """Custom httpx transport that records requests and serves canned responses."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.responses: dict[str, tuple[int, dict]] = {}

    def add_response(self, method: str, path: str, status: int, json_body: dict):
        key = f"{method.upper()} {path}"
        self.responses[key] = (status, json_body)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.raw_path.decode()}"
        if key in self.responses:
            status, body = self.responses[key]
            return httpx.Response(status, json=body, request=request)
        # Default: 404
        return httpx.Response(404, json={"detail": "Not found"}, request=request)


def _make_client(transport: MockTransport, api_key: str = "yaam_test") -> YaaiClient:
    """Create a YaaiClient using a mock transport."""
    client = YaaiClient.__new__(YaaiClient)
    client._credentials = None
    client._google_request = None
    client._base_url = ""
    client._client = httpx.AsyncClient(transport=transport, base_url="http://test", headers={"X-API-Key": api_key})
    return client


class TestClientInit:
    def test_init_with_api_key(self):
        client = YaaiClient("http://localhost:8000/api/v1", api_key="yaam_test")
        assert client._client.headers.get("X-API-Key") == "yaam_test"
        assert client._credentials is None

    def test_init_strips_trailing_slash(self):
        client = YaaiClient("http://localhost:8000/api/v1/", api_key="yaam_test")
        assert client._base_url == "http://localhost:8000/api/v1"

    def test_init_without_api_key_and_no_google_auth_raises(self):
        # google-auth is available in the test environment (server dependency),
        # so we mock it away to verify the ImportError fallback path.
        import unittest.mock

        with unittest.mock.patch.dict("sys.modules", {"google.auth": None, "google.auth.transport.requests": None}):
            with pytest.raises(ImportError, match="google-auth"):
                YaaiClient("http://localhost:8000/api/v1")


class TestClientModels:
    async def test_create_model(self):
        transport = MockTransport()
        model_id = str(uuid.uuid4())
        transport.add_response(
            "POST",
            "/models",
            201,
            {
                "data": {
                    "id": model_id,
                    "name": "test-model",
                    "description": None,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "versions": [],
                }
            },
        )
        client = _make_client(transport)
        result = await client.create_model("test-model")
        assert result.name == "test-model"
        assert str(result.id) == model_id
        # Verify request was sent correctly
        assert len(transport.requests) == 1
        assert transport.requests[0].method == "POST"

    async def test_get_model(self):
        transport = MockTransport()
        model_id = str(uuid.uuid4())
        transport.add_response(
            "GET",
            f"/models/{model_id}",
            200,
            {
                "data": {
                    "id": model_id,
                    "name": "fetched",
                    "description": "desc",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "versions": [],
                }
            },
        )
        client = _make_client(transport)
        result = await client.get_model(uuid.UUID(model_id))
        assert result.name == "fetched"

    async def test_list_models(self):
        transport = MockTransport()
        transport.add_response(
            "GET",
            "/models",
            200,
            {
                "data": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "m1",
                        "description": None,
                        "created_at": "2024-01-01T00:00:00Z",
                        "updated_at": "2024-01-01T00:00:00Z",
                        "versions": [],
                    },
                ]
            },
        )
        client = _make_client(transport)
        result = await client.list_models()
        assert len(result) == 1
        assert result[0].name == "m1"

    async def test_delete_model(self):
        transport = MockTransport()
        model_id = str(uuid.uuid4())
        transport.add_response("DELETE", f"/models/{model_id}", 204, {})
        client = _make_client(transport)
        # Should not raise
        await client.delete_model(uuid.UUID(model_id))
        assert len(transport.requests) == 1


class TestClientInferences:
    async def test_add_inference(self):
        transport = MockTransport()
        version_id = str(uuid.uuid4())
        inf_id = str(uuid.uuid4())
        transport.add_response(
            "POST",
            "/inferences",
            201,
            {
                "data": {
                    "id": inf_id,
                    "model_version_id": version_id,
                    "inputs": {"age": 30},
                    "outputs": {"score": 0.8},
                    "timestamp": "2024-01-01T00:00:00Z",
                    "created_at": "2024-01-01T00:00:00Z",
                }
            },
        )
        client = _make_client(transport)
        result = await client.add_inference(
            uuid.UUID(version_id),
            inputs={"age": 30},
            outputs={"score": 0.8},
        )
        assert str(result.id) == inf_id
        assert str(result.model_version_id) == version_id

    async def test_add_inferences_batch(self):
        transport = MockTransport()
        version_id = str(uuid.uuid4())
        transport.add_response("POST", "/inferences/batch", 201, {"data": {"ingested": 5, "failed": 0, "errors": []}})
        client = _make_client(transport)
        records = [{"inputs": {"x": i}, "outputs": {"y": i * 2}} for i in range(5)]
        result = await client.add_inferences(uuid.UUID(version_id), records)
        assert result.ingested == 5
        assert result.failed == 0


class TestClientReferenceData:
    async def test_add_reference_data(self):
        transport = MockTransport()
        model_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        transport.add_response(
            "POST",
            f"/models/{model_id}/versions/{version_id}/reference-data",
            201,
            {"data": {"ingested": 10, "model_version_id": version_id}},
        )
        client = _make_client(transport)
        records = [{"inputs": {"x": i}, "outputs": {"y": i}} for i in range(10)]
        result = await client.add_reference_data(uuid.UUID(model_id), uuid.UUID(version_id), records)
        assert result.ingested == 10


class TestClientGroundTruth:
    async def test_add_ground_truth(self):
        transport = MockTransport()
        inf_id = str(uuid.uuid4())
        gt_id = str(uuid.uuid4())
        transport.add_response("POST", "/ground-truth", 201, {"data": {"id": gt_id, "inference_id": inf_id}})
        client = _make_client(transport)
        result = await client.add_ground_truth(uuid.UUID(inf_id), label={"class": "fraud"})
        assert result["id"] == gt_id


class TestClientJobs:
    async def test_get_version_job(self):
        transport = MockTransport()
        model_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        transport.add_response(
            "GET",
            f"/models/{model_id}/versions/{version_id}/jobs",
            200,
            {
                "data": [
                    {
                        "id": job_id,
                        "name": "daily-drift",
                        "schedule": "0 2 * * *",
                        "comparison_type": "vs_reference",
                    }
                ]
            },
        )
        client = _make_client(transport)
        result = await client.get_version_job(uuid.UUID(model_id), uuid.UUID(version_id))
        assert result is not None
        assert result["name"] == "daily-drift"

    async def test_get_version_job_none(self):
        transport = MockTransport()
        model_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        transport.add_response("GET", f"/models/{model_id}/versions/{version_id}/jobs", 200, {"data": []})
        client = _make_client(transport)
        result = await client.get_version_job(uuid.UUID(model_id), uuid.UUID(version_id))
        assert result is None

    async def test_get_job(self):
        transport = MockTransport()
        job_id = str(uuid.uuid4())
        transport.add_response("GET", f"/jobs/{job_id}", 200, {"data": {"id": job_id, "name": "daily-drift"}})
        client = _make_client(transport)
        result = await client.get_job(uuid.UUID(job_id))
        assert result["id"] == job_id

    async def test_update_job(self):
        transport = MockTransport()
        job_id = str(uuid.uuid4())
        transport.add_response(
            "PATCH",
            f"/jobs/{job_id}",
            200,
            {"data": {"id": job_id, "name": "updated", "comparison_type": "rolling_window"}},
        )
        client = _make_client(transport)
        result = await client.update_job(uuid.UUID(job_id), name="updated", comparison_type="rolling_window")
        assert result["name"] == "updated"
        assert result["comparison_type"] == "rolling_window"

    async def test_trigger_job(self):
        transport = MockTransport()
        job_id = str(uuid.uuid4())
        transport.add_response(
            "POST", f"/jobs/{job_id}/trigger", 201, {"data": {"id": str(uuid.uuid4()), "status": "completed"}}
        )
        client = _make_client(transport)
        result = await client.trigger_job(uuid.UUID(job_id))
        assert result["status"] == "completed"

    async def test_backfill_job(self):
        transport = MockTransport()
        job_id = str(uuid.uuid4())
        transport.add_response("POST", f"/jobs/{job_id}/backfill", 201, {"data": {"runs_created": 4}})
        client = _make_client(transport)
        result = await client.backfill_job(uuid.UUID(job_id))
        assert result["runs_created"] == 4


class TestClientErrorHandling:
    async def test_raises_on_404(self):
        transport = MockTransport()
        client = _make_client(transport)
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_model(uuid.uuid4())

    async def test_raises_on_500(self):
        transport = MockTransport()
        transport.add_response("GET", "/models", 500, {"detail": "Internal error"})
        client = _make_client(transport)
        with pytest.raises(httpx.HTTPStatusError):
            await client.list_models()


class TestClientContextManager:
    async def test_async_context_manager(self):
        async with YaaiClient("http://localhost:8000", api_key="yaam_test") as client:
            assert client._client is not None
        # After exiting, client should be closed (aclose called)


class TestClientCredentialRefresh:
    async def test_refresh_noop_when_no_credentials(self):
        transport = MockTransport()
        transport.add_response("GET", "/models", 200, {"data": []})
        client = _make_client(transport)
        # _refresh_google_credentials should be no-op
        client._refresh_google_credentials()
        result = await client.list_models()
        assert result == []
