<p align="center">
  <img src="docs/assets/banner-bordered.svg" alt="YAAI Monitoring" width="480">
</p>

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
pip install yaai-monitoring

# uv
uv add yaai-monitoring
```

This installs just `httpx` and `pydantic`. No heavy dependencies. If you authenticate with Google service accounts instead of API keys, install with `pip install yaai-monitoring[gcp]` to add `google-auth`.

### Server (includes SDK)

For running the full monitoring platform:

```bash
# pip
pip install yaai-monitoring[server]

# uv
uv add yaai-monitoring[server]
```

This pulls in FastAPI, SQLAlchemy, scikit-learn, and friends. You'll also need PostgreSQL.


## Quick Start with Docker

The fastest way to get the full platform running:

```bash
git clone https://github.com/Maxl94/yaai.git
cd yaai
cp .env.example .env
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
export DATABASE_URL_SYNC="postgresql://user:pass@localhost:5432/yaai"

# Start the server
uvicorn yaai.server.main:app --host 0.0.0.0 --port 8000
```

Database migrations are applied automatically on startup via [Alembic](https://alembic.sqlalchemy.org/). No manual migration step needed. Set `AUTO_MIGRATE=false` to disable this and run migrations yourself (`alembic upgrade head`).

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
                SchemaFieldCreate(field_name="is_fraud", direction="output", data_type="categorical"),
            ],
        )

        # Log a single inference
        inference = await client.add_inference(
            model_version_id=version.id,
            inputs={"amount": 150.0, "country": "DE"},
            outputs={"is_fraud": "false"},
        )

        # Or log a batch
        await client.add_inferences(
            model_version_id=version.id,
            records=[
                {"inputs": {"amount": 42.0, "country": "US"}, "outputs": {"is_fraud": "false"}},
                {"inputs": {"amount": 9001.0, "country": "NG"}, "outputs": {"is_fraud": "true"}},
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
| `get_version_job(model_id, model_version_id)` | Get the drift job for a version |
| `get_job(job_id)` | Fetch job details |
| `update_job(job_id, **fields)` | Update job configuration |
| `trigger_job(job_id)` | Trigger a drift detection run |
| `backfill_job(job_id)` | Trigger historical drift backfill |
| `infer_schema(sample)` | Infer schema from a single sample |
| `infer_schema_batch(samples)` | Infer schema from multiple samples |
| `validate_schema(schema_fields, inputs, outputs)` | Validate a record against an inline schema |
| `validate_schema_batch(schema_fields, records)` | Validate a batch against an inline schema |
| `validate_model_version_schema(model_id, version_id, inputs, outputs)` | Validate a record against a version's schema |
| `validate_model_version_schema_batch(model_id, version_id, records)` | Validate a batch against a version's schema |

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
      {"field_name": "is_fraud", "direction": "output", "data_type": "categorical"}
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
- **Auth** — local accounts, Google OAuth, API keys, Google service accounts

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

pip install yaai-monitoring          → just the SDK (httpx + pydantic)
pip install yaai-monitoring[server]  → everything above
```

## Development

There are two ways to run YAAI locally, depending on what you need:

| | **Local dev servers** (recommended for development) | **Docker Compose** |
|---|---|---|
| **What runs** | Backend + frontend as separate processes with hot-reload | Everything in Docker containers |
| **Frontend hot-reload** | Yes — instant feedback on UI changes | No — rebuild required |
| **Backend hot-reload** | Yes — auto-restarts on Python changes | No — rebuild required |
| **Google OAuth** | Does not work (different origins) | Works |
| **Auth for development** | API key or local accounts | Any (including Google OAuth) |
| **Prerequisites** | Python 3.12+, Node.js 20+, Docker, [uv](https://docs.astral.sh/uv/) | Docker only |

> **Why can't Google OAuth work with local dev servers?** The frontend (port 3000) and backend (port 8000) run on different origins. OAuth redirects require a single origin, which only works when the backend serves the frontend itself (same port). For day-to-day development this doesn't matter — use API key auth or local accounts instead.

### Option A: Local dev servers (recommended)

Best for active development — you get hot-reload on both frontend and backend.

#### 1. Start the database

```bash
docker compose up db -d
```

This starts **only** the PostgreSQL database in Docker, exposed on port **5431** (not the default 5432, to avoid conflicts with any local PostgreSQL).

> **Don't run `docker compose up` without `db`** — that also starts the backend in Docker and blocks port 8000.

#### 2. Install dependencies

```bash
# Backend (SDK + server + dev tools)
uv sync

# Frontend
cd frontend && npm ci && cd ..
```

#### 3. Configure environment

```bash
cp .env.example .env
```

The example config has Google OAuth **disabled** and API key auth **enabled** — that's all you need for local development. No Google credentials required. All auth settings use the `AUTH_` prefix (see `.env.example` for the full list).

#### 4. Start the backend

```bash
uv run uvicorn yaai.server.main:app --reload --reload-dir yaai --host 0.0.0.0 --port 8000
```

The API server starts on **http://localhost:8000** with auto-reload. API docs are at **http://localhost:8000/docs**.

> **"Address already in use"?** Port 8000 is already taken — most likely by the Docker backend container. Make sure you started only `docker compose up db -d` (not the full stack). Check with `lsof -i :8000` and stop the conflicting process, or use a different port (e.g. `--port 8001`). If you change the backend port, also update the proxy target in [frontend/vite.config.ts](frontend/vite.config.ts).

#### 5. Start the frontend (separate terminal)

```bash
cd frontend && npm run dev
```

The Vue dev server runs on **http://localhost:3000** and proxies `/api` requests to the backend on port 8000. Open **http://localhost:3000** in your browser.

### Option B: Docker Compose

Best for testing the full stack as-is, or when you need Google OAuth. No Python or Node.js install required — just Docker.

```bash
# Start everything (builds frontend + backend into one container)
docker compose up --build
```

Open **http://localhost:8000**. The backend serves the frontend on the same origin, so Google OAuth works.

To use Google OAuth, set these variables in your `.env` file:
- `AUTH_OAUTH_GOOGLE_ENABLED=true`
- `AUTH_OAUTH_GOOGLE_CLIENT_ID` and `AUTH_OAUTH_GOOGLE_CLIENT_SECRET` to your Google Cloud credentials
- The OAuth redirect URI in Google Cloud Console to `http://localhost:8000/api/v1/auth/oauth/google/callback`

### Option A+B hybrid: Build frontend locally, serve from backend

If you want Google OAuth without Docker but don't need frontend hot-reload:

```bash
# Build the frontend
cd frontend && npm run build-only && cd ..

# Copy the build output into the backend's static directory
cp -r frontend/dist/* yaai/server/static/

# Start the backend (serves both API and frontend on port 8000)
uv run uvicorn yaai.server.main:app --reload --reload-dir yaai --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000**. You'll need to rebuild and copy again after frontend changes.

### Running tests

```bash
# Backend tests
uv run pytest

# Linting
uv run ruff check .

# Frontend type-checking
cd frontend && npm run type-check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for commit conventions and PR guidelines.

## License

[Elastic License 2.0](LICENSE)
