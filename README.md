<p align="center">
  <img src="docs/logo.svg" alt="YAAI Monitoring" width="380">
</p>

<h1 align="center">YAAI Monitoring</h1>

<p align="center">
  <strong>Yet Another AI Monitoring</strong> — because the existing ones didn't fit and building your own seemed like a good idea at the time.
</p>

![Models Overview](docs/screenshots/models.jpeg)

## Why This Exists

I wanted ML monitoring that's:
- **REST-based** — send JSON, done
- **Auto-everything** — dashboards, drift detection, comparisons generated from your schema
- **Zero config** — no YAML files, no property mappings, no pipeline integrations (except server config)

Define your fields once (or let YAAI guess them), send data, get insights.

## When to Use YAAI

Use this if you:
- Want monitoring up and running in minutes, not days
- Prefer REST APIs over SDK-heavy integrations
- Don't want to configure dashboards manually
- Need drift detection without becoming a drift detection expert
- Value simplicity over feature completeness

## When NOT to Use YAAI

This might not be for you if you need:
- **Deep ML pipeline integration** — check out [Evidently](https://github.com/evidentlyai/evidently)
- **Custom drift algorithms** — we use standard methods (PSI, KS, Chi-squared, JS divergence)
- **Multi-tenant SaaS deployment** — this is self-hosted, single-tenant
- **Battle-tested production stability** — this is young software, treat it accordingly

Those tools are more powerful. YAAI is more opinionated and simpler.

## Installation

YAAI ships as two things: a lightweight **Python SDK** and a self-hosted **monitoring server**.

### SDK only

For sending inference data from your services:

```bash
# pip
pip install yaai

# uv
uv add yaai
```

This installs just `httpx` and `pydantic`. No heavy dependencies. If you authenticate with Google service accounts instead of API keys, install with `pip install yaai[gcp]` to add `google-auth`.

### Server (includes SDK)

For running the full monitoring platform:

```bash
# pip
pip install yaai[server]

# uv
uv add yaai[server]
```

This pulls in FastAPI, SQLAlchemy, scikit-learn, and friends. You'll also need PostgreSQL.

> **Note:** YAAI is not on PyPI yet. For now, install from source — see [Development](#development).

## Quick Start with Docker

The fastest way to get the full platform running:

```bash
git clone https://github.com/mballuff/yaai-monitoring.git
cd yaai-monitoring
docker compose up -d

# Open http://localhost:8000
```

### Load Demo Data

Two scripts are included — they produce identical results, one uses raw HTTP, the other uses the SDK:

```bash
uv sync

# Via REST API (httpx)
uv run scripts/generate_demo_data.py --drop-all --mode full --dataset all

# Via Python SDK (yaai.YaaiClient)
API_KEY=your_key uv run scripts/generate_demo_data_sdk.py --drop-all --mode full --dataset all
```

## Running the Server

If you'd rather not use Docker:

```bash
# You need PostgreSQL running somewhere
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/yaai"

# Start the server
uvicorn yaai.server.main:app --host 0.0.0.0 --port 8000
```

The server ships with the frontend baked in — no separate web server needed. Just open `http://localhost:8000` in your browser.

Full API docs at `http://localhost:8000/docs`.

## Using the SDK

The SDK is async. It handles model registration and inference logging for service accounts.

### Authentication

```python
# Option 1: Explicit API key
client = YaaiClient("http://localhost:8000/api/v1", api_key="yaam_...")

# Option 2: Google Application Default Credentials (requires yaai[gcp])
# Uses GOOGLE_APPLICATION_CREDENTIALS env var, workload identity, or GCP metadata server
client = YaaiClient("http://localhost:8000/api/v1")
```

When no `api_key` is passed, the client automatically uses Google ADC. Tokens are refreshed transparently before they expire. The server must have Google service account auth enabled and the SA email allowlisted — see the auth configuration docs.

### Example

```python
import asyncio
from yaai import YaaiClient
from yaai.schemas.model import SchemaFieldCreate

async def main():
    async with YaaiClient("http://localhost:8000/api/v1", api_key="yaam_...") as client:

        # Create a model
        model = await client.create_model("fraud-detector")

        # Define a version with schema
        version = await client.create_model_version(
            model_id=model.id,
            version="v1.0",
            schema_fields=[
                SchemaFieldCreate(field_name="amount", direction="input", data_type="numerical"),
                SchemaFieldCreate(field_name="country", direction="input", data_type="categorical"),
                SchemaFieldCreate(field_name="is_fraud", direction="output", data_type="boolean"),
            ],
        )

        # Log a single inference
        inference = await client.add_inference(
            model_version_id=version.id,
            inputs={"amount": 150.0, "country": "DE"},
            outputs={"is_fraud": False},
        )

        # Or log a batch
        await client.add_inferences(
            model_version_id=version.id,
            records=[
                {"inputs": {"amount": 42.0, "country": "US"}, "outputs": {"is_fraud": False}},
                {"inputs": {"amount": 9001.0, "country": "NG"}, "outputs": {"is_fraud": True}},
            ],
        )

asyncio.run(main())
```

### SDK Methods

| Method | What it does |
|---|---|
| `create_model(name)` | Register a new model |
| `get_model(model_id)` | Fetch model details |
| `list_models()` | List all models |
| `delete_model(model_id)` | Delete a model and all its data |
| `create_model_version(model_id, version, schema_fields)` | Create a versioned schema |
| `add_inference(model_version_id, inputs, outputs)` | Log one inference |
| `add_inferences(model_version_id, records)` | Log a batch of inferences |
| `add_reference_data(model_id, model_version_id, records)` | Upload reference/baseline data |
| `add_ground_truth(inference_id, label)` | Attach ground truth to an inference |
| `list_jobs(model_id, model_version_id)` | List drift detection jobs |
| `backfill_job(job_id)` | Trigger historical drift backfill |

The SDK is intentionally minimal. It covers what a service account should do: register models, send data. The dashboards, drift detection, and alerting happen server-side automatically.

## Using the REST API Directly

No SDK required. The API accepts plain JSON — use curl, httpx, requests, or whatever you like:

```bash
# Create a model
curl -X POST http://localhost:8000/api/v1/models \
  -H "Content-Type: application/json" \
  -H "X-API-Key: yaam_..." \
  -d '{"name": "fraud-detector"}'

# Add a version with schema
curl -X POST http://localhost:8000/api/v1/models/{model_id}/versions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: yaam_..." \
  -d '{
    "version": "v1.0",
    "schema": [
      {"field_name": "amount", "direction": "input", "data_type": "numerical"},
      {"field_name": "country", "direction": "input", "data_type": "categorical"},
      {"field_name": "is_fraud", "direction": "output", "data_type": "boolean"}
    ]
  }'

# Send inference data
curl -X POST http://localhost:8000/api/v1/inferences \
  -H "Content-Type: application/json" \
  -H "X-API-Key: yaam_..." \
  -d '{
    "model_version_id": "{version_id}",
    "inputs": {"amount": 150.0, "country": "DE"},
    "outputs": {"is_fraud": false}
  }'

# Send a batch
curl -X POST http://localhost:8000/api/v1/inferences/batch \
  -H "Content-Type: application/json" \
  -H "X-API-Key: yaam_..." \
  -d '{
    "model_version_id": "{version_id}",
    "records": [
      {"inputs": {"amount": 42.0, "country": "US"}, "outputs": {"is_fraud": false}},
      {"inputs": {"amount": 9001.0, "country": "NG"}, "outputs": {"is_fraud": true}}
    ]
  }'
```

Full interactive API docs at `http://localhost:8000/docs` (Swagger UI).

## Screenshots

### Dashboard
![Dashboard](docs/screenshots/model_version_dashboard.jpeg)

### Drift Detection
![Drift](docs/screenshots/drift_dashboard.jpeg)

## Features

- **Schema-driven** — define fields once, everything else is automatic
- **Drift detection** — PSI, KS test, Chi-squared, Jensen-Shannon divergence
- **Scheduled jobs** — cron-based checks with configurable windows
- **Auto-dashboards** — per-feature distribution charts
- **Time comparisons** — compare any two periods side by side
- **Alerting** — threshold-based notifications
- **Auth** — Google OAuth + local accounts + service account API keys

## Architecture

```
┌──────────────────────────────────────────┐
│            Vue 3 Frontend (SPA)          │
│     Vuetify · ECharts · TypeScript       │
├──────────────────────────────────────────┤
│            FastAPI Backend               │
│   REST API · APScheduler · Drift Engine  │
├──────────────────────────────────────────┤
│              PostgreSQL 16               │
│          JSONB inference storage          │
└──────────────────────────────────────────┘

pip install yaai          → just the SDK (httpx + pydantic)
pip install yaai[server]  → everything above
```

## Development

```bash
# Start database
docker compose up db -d

# Install all dependencies (SDK + server + dev tools)
uv sync

# Backend
uv run uvicorn yaai.server.main:app --reload --reload-dir yaai

# Frontend (separate terminal)
cd frontend && npm ci && npm run dev
```

The frontend dev server proxies `/api` to the backend on port 8000, so both hot-reload independently.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

[Apache License 2.0](LICENSE)
