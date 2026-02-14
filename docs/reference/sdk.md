# Python SDK

The SDK is a thin async client. It covers what a service account needs to do: register models, send data, upload baselines. Dashboards, drift detection, and alerting happen server-side automatically.

## Install

```bash
pip install yaai          # just the client (httpx + pydantic)
pip install yaai[gcp]     # adds google-auth for GCP service accounts
```

## Authentication

Two options:

```python
# Explicit API key (recommended for most setups)
client = YaaiClient("http://localhost:8000/api/v1", api_key="yaam_...")

# Google Application Default Credentials (requires yaai[gcp])
# Uses GOOGLE_APPLICATION_CREDENTIALS, workload identity, or GCP metadata server
client = YaaiClient("http://localhost:8000/api/v1")
```

When no `api_key` is passed, the client uses Google ADC and refreshes tokens automatically.

## Usage

The client is an async context manager:

```python
import asyncio
from yaai import YaaiClient
from yaai.schemas.model import SchemaFieldCreate

async def main():
    async with YaaiClient("http://localhost:8000/api/v1", api_key="yaam_...") as client:

        # Register a model
        model = await client.create_model("fraud-detector")

        # Create a version with schema
        version = await client.create_model_version(
            model_id=model.id,
            version="v1.0",
            schema_fields=[
                SchemaFieldCreate(field_name="amount", direction="input", data_type="numerical"),
                SchemaFieldCreate(field_name="country", direction="input", data_type="categorical"),
                SchemaFieldCreate(field_name="is_fraud", direction="output", data_type="categorical"),
            ],
        )

        # Log a single inference
        await client.add_inference(
            model_version_id=version.id,
            inputs={"amount": 150.0, "country": "DE"},
            outputs={"is_fraud": "false"},
        )

        # Log a batch (up to 1000 records)
        await client.add_inferences(
            model_version_id=version.id,
            records=[
                {"inputs": {"amount": 42.0, "country": "US"}, "outputs": {"is_fraud": "false"}},
                {"inputs": {"amount": 9001.0, "country": "NG"}, "outputs": {"is_fraud": "true"}},
            ],
        )

        # Upload reference data (training distribution)
        await client.add_reference_data(
            model_id=model.id,
            model_version_id=version.id,
            records=[
                {"inputs": {"amount": 85.0, "country": "DE"}, "outputs": {"is_fraud": "false"}},
                # ... typically hundreds or thousands of records
            ],
        )

asyncio.run(main())
```

## Methods at a glance

| Method | What it does |
|---|---|
| `create_model(name)` | Register a new model |
| `get_model(model_id)` | Fetch model details |
| `list_models()` | List all models |
| `delete_model(model_id)` | Delete a model and all its data |
| `create_model_version(model_id, version, schema_fields)` | Create a versioned schema |
| `add_inference(model_version_id, inputs, outputs)` | Log one inference |
| `add_inferences(model_version_id, records)` | Log a batch of inferences |
| `add_reference_data(model_id, model_version_id, records)` | Upload baseline data |
| `add_ground_truth(inference_id, label)` | Attach ground truth to an inference |
| `list_jobs(model_id, model_version_id)` | List drift detection jobs |
| `backfill_job(job_id)` | Trigger historical drift backfill |

## Full API reference

Auto-generated from source:

::: yaai.client.YaaiClient
    options:
      show_root_heading: true
      members_order: source
      show_source: true
      docstring_style: google
