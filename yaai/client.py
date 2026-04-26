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
    ModelVersionSummary,
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
    Default Credentials (ADC). When no ``api_key`` is provided the client
    tries to obtain credentials via ``google.auth.default()`` — install
    ``yaai[gcp]`` to enable this.

    When ``target_audience`` is provided (recommended for Google SA auth),
    the client requests an ID token scoped to that audience. The audience
    must match the server's configured
    ``GOOGLE_SA_AUDIENCE``.

    Usage::

        # With API key
        async with YaaiClient("http://localhost:8000/api/v1", api_key="yaam_...") as client:
            model = await client.create_model("my-model")

        # With Google ADC + ID token (recommended for service accounts)
        async with YaaiClient("http://localhost:8000/api/v1", target_audience="https://yaai.example.com") as client:
            model = await client.create_model("my-model")

        # With Google user ADC (ID token)
        async with YaaiClient("http://localhost:8000/api/v1") as client:
            model = await client.create_model("my-model")

        # With a longer timeout for slow server responses
        async with YaaiClient("http://localhost:8000/api/v1", api_key="yaam_...", timeout=60.0) as client:
            model = await client.create_model("my-model")
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        target_audience: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._credentials = None
        self._google_request = None

        if api_key is not None:
            headers: dict[str, str] = {"X-API-Key": api_key}
        else:
            headers = self._init_google_credentials(target_audience)

        self._client = httpx.AsyncClient(base_url=self._base_url, headers=headers, timeout=timeout)

    def _init_google_credentials(self, target_audience: str | None = None) -> dict[str, str]:
        """Obtain Google ADC and return initial auth headers."""
        try:
            import google.auth  # noqa: PLC0415
            import google.auth.transport.requests  # noqa: PLC0415
            from google.auth import exceptions as google_auth_exceptions  # noqa: PLC0415  # noqa: PLC0415
            from google.oauth2 import id_token as google_id_token  # noqa: PLC0415
        except ImportError as exc:
            msg = (
                "No api_key provided and google-auth is not installed. "
                "Either pass api_key= or install yaai[gcp] for Google "
                "Application Default Credentials."
            )
            raise ImportError(msg) from exc

        self._google_request = google.auth.transport.requests.Request()
        credentials, _ = google.auth.default()

        if target_audience:
            try:
                self._credentials = google_id_token.fetch_id_token_credentials(
                    target_audience,
                    request=self._google_request,
                )
            except google_auth_exceptions.DefaultCredentialsError:
                if hasattr(credentials, "with_target_audience"):
                    self._credentials = credentials.with_target_audience(target_audience)
                else:
                    self._credentials = credentials
        else:
            self._credentials = credentials

        self._credentials.refresh(self._google_request)
        token = self._current_google_token()
        if not token:
            if target_audience:
                msg = (
                    "Could not obtain an ID token for the configured target_audience. "
                    "Cloud Run and service-account credentials should use metadata or "
                    "GOOGLE_APPLICATION_CREDENTIALS; user ADC falls back to a generic "
                    "Google ID token when available."
                )
            else:
                msg = "Could not obtain an ID token from user credentials. Run: gcloud auth application-default login"
            raise RuntimeError(msg)

        return {"Authorization": f"Bearer {token}"}

    def _current_google_token(self) -> str | None:
        """Return the current Google bearer token for the active credential."""
        if self._credentials is None:
            return None

        token = getattr(self._credentials, "id_token", None)
        if token:
            return token

        return getattr(self._credentials, "token", None)

    def _refresh_google_credentials(self) -> None:
        """Refresh Google credentials if expired. No-op for API key auth."""
        if self._credentials is None:
            return
        if not self._credentials.valid:
            self._credentials.refresh(self._google_request)
            token = self._current_google_token()
            self._client.headers["Authorization"] = f"Bearer {token}"

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
        if response.is_error:
            try:
                body = response.json()
                detail = body.get("detail", response.text) if isinstance(body, dict) else response.text
            except Exception:
                detail = response.text
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

    async def get_version(
        self,
        model_id: uuid.UUID,
        version_id: uuid.UUID,
    ) -> ModelVersionRead:
        """Fetch full details for a specific model version."""
        resp = await self._request("GET", f"/models/{model_id}/versions/{version_id}")
        return ModelVersionRead.model_validate(resp.json()["data"])

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

    async def get_version_by_label(
        self,
        model_id: uuid.UUID,
        version: str,
    ) -> ModelVersionSummary | None:
        """Look up a model version by its label.

        Returns the :class:`ModelVersionSummary` if a version with the given
        label exists, or ``None`` otherwise.
        """
        model = await self.get_model(model_id)
        return next((v for v in model.versions if v.version == version), None)

    async def get_or_create_version(
        self,
        model_id: uuid.UUID,
        version: str,
        *,
        sample_data: dict[str, dict] | None = None,
        schema_fields: list[SchemaFieldCreate] | None = None,
        description: str | None = None,
        keep_previous_active: bool = False,
    ) -> ModelVersionRead | ModelVersionSummary:
        """Idempotent version upsert: return existing or create new.

        Always requires exactly one of ``sample_data`` or ``schema_fields``
        so the call is deterministic regardless of server state.  If the
        version already exists the creation parameters are ignored and the
        existing :class:`ModelVersionSummary` is returned.  If it doesn't
        exist, a new version is created from the provided schema info.

        For a pure lookup without creation parameters, use
        :meth:`get_version_by_label` instead.

        Args:
            model_id: The UUID of the parent model.
            version: Human-readable version label (e.g. ``"v2.0"``).
            sample_data: A dict with ``"inputs"`` and ``"outputs"`` keys used
                to infer the schema.  Mutually exclusive with
                ``schema_fields``.
            schema_fields: An explicit list of :class:`SchemaFieldCreate`
                objects defining the version's schema.  Mutually exclusive
                with ``sample_data``.
            description: Optional description for the new version.
            keep_previous_active: If *True*, existing active versions stay
                active when creating a new version.

        Returns:
            The matched :class:`ModelVersionSummary` if the version already
            exists, or a freshly created :class:`ModelVersionRead`.

        Raises:
            ValueError: If both ``sample_data`` and ``schema_fields`` are
                provided, or if neither is provided.
        """
        if sample_data is not None and schema_fields is not None:
            msg = "sample_data and schema_fields are mutually exclusive. Provide one or the other, not both."
            raise ValueError(msg)

        if sample_data is None and schema_fields is None:
            msg = (
                "Either sample_data or schema_fields must be provided. "
                "Pass sample_data={'inputs': {...}, 'outputs': {...}} to "
                "auto-infer the schema, or pass schema_fields=[...] to "
                "define it explicitly. For a pure lookup use "
                "get_version_by_label() instead."
            )
            raise ValueError(msg)

        model = await self.get_model(model_id)
        for v in model.versions:
            if v.version == version:
                return v

        # Version doesn't exist — create it
        if schema_fields is not None:
            return await self.create_model_version(
                model_id,
                version,
                schema_fields,
                description=description,
                keep_previous_active=keep_previous_active,
            )

        inferred = await self.infer_schema(sample_data)
        return await self.create_model_version(
            model_id,
            version,
            inferred.schema_fields,
            description=description,
            keep_previous_active=keep_previous_active,
        )

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
