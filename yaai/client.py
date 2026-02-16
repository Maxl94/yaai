"""Async SDK client for the yaai monitoring platform."""

from __future__ import annotations

import uuid

import httpx

from yaai.schemas.inference import (
    GroundTruthCreate,
    InferenceBatchCreate,
    InferenceBatchResult,
    InferenceCreate,
    InferenceRead,
    ReferenceDataResult,
    ReferenceDataUpload,
)
from yaai.schemas.model import (
    BatchValidationResult,
    InferSchemaBatchRequest,
    InferSchemaResponse,
    ModelCreate,
    ModelRead,
    ModelVersionCreate,
    ModelVersionRead,
    SchemaFieldCreate,
    ValidateModelVersionBatchRequest,
    ValidateModelVersionRequest,
    ValidateSchemaBatchRequest,
    ValidateSchemaRequest,
    ValidationResult,
)


class YaaiClient:
    """Async client for the yaai monitoring API.

    Authenticates with either an explicit API key or Google Application
    Default Credentials (ADC).  When no ``api_key`` is provided the client
    tries to obtain credentials via ``google.auth.default()`` — install
    ``yaai[gcp]`` to enable this.

    When ``target_audience`` is provided (recommended for Google SA auth),
    the client requests an ID token scoped to that audience instead of a
    generic access token.  The audience must match the server's configured
    ``GOOGLE_SA_AUDIENCE``.

    Usage::

        # With API key
        async with YaaiClient("http://localhost:8000/api/v1", api_key="yaam_...") as client:
            model = await client.create_model("my-model")

        # With Google ADC + ID token (recommended for service accounts)
        async with YaaiClient("http://localhost:8000/api/v1", target_audience="https://yaai.example.com") as client:
            model = await client.create_model("my-model")

        # With Google ADC (access token fallback)
        async with YaaiClient("http://localhost:8000/api/v1") as client:
            model = await client.create_model("my-model")
    """

    def __init__(self, base_url: str, *, api_key: str | None = None, target_audience: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._credentials = None
        self._google_request = None

        if api_key is not None:
            headers: dict[str, str] = {"X-API-Key": api_key}
        else:
            headers = self._init_google_credentials(target_audience)

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
        )

    def _init_google_credentials(self, target_audience: str | None = None) -> dict[str, str]:
        """Obtain Google ADC and return initial auth headers."""
        try:
            import google.auth  # noqa: PLC0415
            import google.auth.transport.requests  # noqa: PLC0415
        except ImportError as exc:
            msg = (
                "No api_key provided and google-auth is not installed. "
                "Either pass api_key= or install yaai[gcp] for Google "
                "Application Default Credentials."
            )
            raise ImportError(msg) from exc

        self._google_request = google.auth.transport.requests.Request()
        credentials, _ = google.auth.default()

        if target_audience and hasattr(credentials, "with_target_audience"):
            # Service account credentials support ID tokens
            self._credentials = credentials.with_target_audience(target_audience)
        else:
            self._credentials = credentials

        self._credentials.refresh(self._google_request)
        return {"Authorization": f"Bearer {self._credentials.token}"}

    def _refresh_google_credentials(self) -> None:
        """Refresh Google credentials if expired. No-op for API key auth."""
        if self._credentials is None:
            return
        if not self._credentials.valid:
            self._credentials.refresh(self._google_request)
            self._client.headers["Authorization"] = f"Bearer {self._credentials.token}"

    async def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """Send a request with automatic credential refresh."""
        self._refresh_google_credentials()
        resp = await self._client.request(method, url, **kwargs)
        self._raise_for_status(resp)
        return resp

    async def __aenter__(self) -> YaaiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            detail = response.json().get("detail", response.text)
            raise httpx.HTTPStatusError(
                f"{response.status_code}: {detail}",
                request=response.request,
                response=response,
            )

    # -- Models --

    async def create_model(self, name: str, description: str | None = None) -> ModelRead:
        payload = ModelCreate(name=name, description=description)
        resp = await self._request("POST", "/models", json=payload.model_dump())
        return ModelRead.model_validate(resp.json()["data"])

    async def get_model(self, model_id: uuid.UUID) -> ModelRead:
        resp = await self._request("GET", f"/models/{model_id}")
        return ModelRead.model_validate(resp.json()["data"])

    async def list_models(self) -> list[ModelRead]:
        resp = await self._request("GET", "/models")
        return [ModelRead.model_validate(m) for m in resp.json()["data"]]

    async def delete_model(self, model_id: uuid.UUID) -> None:
        await self._request("DELETE", f"/models/{model_id}")

    # -- Versions --

    async def create_model_version(
        self,
        model_id: uuid.UUID,
        version: str,
        schema_fields: list[SchemaFieldCreate],
        *,
        description: str | None = None,
        keep_previous_active: bool = False,
    ) -> ModelVersionRead:
        payload = ModelVersionCreate(
            version=version,
            schema_fields=schema_fields,
            description=description,
            keep_previous_active=keep_previous_active,
        )
        resp = await self._request(
            "POST",
            f"/models/{model_id}/versions",
            json=payload.model_dump(by_alias=True),
        )
        return ModelVersionRead.model_validate(resp.json()["data"])

    # -- Inferences --

    async def add_inference(
        self,
        model_version_id: uuid.UUID,
        inputs: dict,
        outputs: dict,
    ) -> InferenceRead:
        payload = InferenceCreate(
            model_version_id=model_version_id,
            inputs=inputs,
            outputs=outputs,
        )
        resp = await self._request("POST", "/inferences", json=payload.model_dump(mode="json"))
        return InferenceRead.model_validate(resp.json()["data"])

    async def add_inferences(
        self,
        model_version_id: uuid.UUID,
        records: list[dict],
    ) -> InferenceBatchResult:
        payload = InferenceBatchCreate(
            model_version_id=model_version_id,
            records=records,
        )
        resp = await self._request("POST", "/inferences/batch", json=payload.model_dump(mode="json"))
        return InferenceBatchResult.model_validate(resp.json()["data"])

    # -- Reference data --

    async def add_reference_data(
        self,
        model_id: uuid.UUID,
        model_version_id: uuid.UUID,
        records: list[dict],
    ) -> ReferenceDataResult:
        payload = ReferenceDataUpload(records=records)
        resp = await self._request(
            "POST",
            f"/models/{model_id}/versions/{model_version_id}/reference-data",
            json=payload.model_dump(mode="json"),
        )
        return ReferenceDataResult.model_validate(resp.json()["data"])

    # -- Ground truth --

    async def add_ground_truth(
        self,
        inference_id: uuid.UUID,
        label: dict,
    ) -> dict:
        payload = GroundTruthCreate(inference_id=inference_id, label=label)
        resp = await self._request("POST", "/ground-truth", json=payload.model_dump(mode="json"))
        return resp.json()["data"]

    # -- Jobs --

    async def get_version_job(
        self,
        model_id: uuid.UUID,
        model_version_id: uuid.UUID,
    ) -> dict | None:
        """Get the single job for a model version, or None if none exists."""
        resp = await self._request("GET", f"/models/{model_id}/versions/{model_version_id}/jobs")
        jobs = resp.json()["data"]
        return jobs[0] if jobs else None

    async def get_job(self, job_id: uuid.UUID) -> dict:
        resp = await self._request("GET", f"/jobs/{job_id}")
        return resp.json()["data"]

    async def update_job(self, job_id: uuid.UUID, **fields: object) -> dict:
        resp = await self._request("PATCH", f"/jobs/{job_id}", json=fields)
        return resp.json()["data"]

    async def trigger_job(self, job_id: uuid.UUID) -> dict:
        resp = await self._request("POST", f"/jobs/{job_id}/trigger")
        return resp.json()["data"]

    async def backfill_job(self, job_id: uuid.UUID) -> dict:
        resp = await self._request("POST", f"/jobs/{job_id}/backfill", timeout=300.0)
        return resp.json()["data"]

    # -- Schema inference --

    async def infer_schema(self, sample: dict[str, dict]) -> InferSchemaResponse:
        resp = await self._request("POST", "/schema/infer", json={"sample": sample})
        return InferSchemaResponse.model_validate(resp.json()["data"])

    async def infer_schema_batch(self, samples: list[dict[str, dict]]) -> InferSchemaResponse:
        payload = InferSchemaBatchRequest(samples=samples)
        resp = await self._request("POST", "/schema/infer/batch", json=payload.model_dump())
        return InferSchemaResponse.model_validate(resp.json()["data"])

    # -- Schema validation (general) --

    async def validate_schema(
        self,
        schema_fields: list[SchemaFieldCreate],
        inputs: dict,
        outputs: dict,
    ) -> ValidationResult:
        payload = ValidateSchemaRequest(schema_fields=schema_fields, inputs=inputs, outputs=outputs)
        resp = await self._request("POST", "/schema/validate", json=payload.model_dump(by_alias=True))
        return ValidationResult.model_validate(resp.json()["data"])

    async def validate_schema_batch(
        self,
        schema_fields: list[SchemaFieldCreate],
        records: list[dict],
    ) -> BatchValidationResult:
        payload = ValidateSchemaBatchRequest(schema_fields=schema_fields, records=records)
        resp = await self._request("POST", "/schema/validate/batch", json=payload.model_dump(by_alias=True))
        return BatchValidationResult.model_validate(resp.json()["data"])

    # -- Schema validation (model version) --

    async def validate_model_version_schema(
        self,
        model_id: uuid.UUID,
        version_id: uuid.UUID,
        inputs: dict,
        outputs: dict,
    ) -> ValidationResult:
        payload = ValidateModelVersionRequest(inputs=inputs, outputs=outputs)
        resp = await self._request(
            "POST",
            f"/models/{model_id}/versions/{version_id}/schema/validate",
            json=payload.model_dump(),
        )
        return ValidationResult.model_validate(resp.json()["data"])

    async def validate_model_version_schema_batch(
        self,
        model_id: uuid.UUID,
        version_id: uuid.UUID,
        records: list[dict],
    ) -> BatchValidationResult:
        payload = ValidateModelVersionBatchRequest(records=records)
        resp = await self._request(
            "POST",
            f"/models/{model_id}/versions/{version_id}/schema/validate/batch",
            json=payload.model_dump(),
        )
        return BatchValidationResult.model_validate(resp.json()["data"])
