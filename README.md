<p align="center">
  <img src="https://raw.githubusercontent.com/Maxl94/yaai/main/docs/assets/banner-bordered.svg" alt="YAAI Monitoring" width="480">
</p>

<p align="center">
  <strong>Yet Another AI Monitoring</strong> — because the existing ones didn't fit and building your own seemed like a good idea at the time.
</p>

<p align="center">
  <a href="https://maxl94.github.io/yaai/">Documentation</a> &nbsp;·&nbsp;
  <a href="https://maxl94.github.io/yaai/getting-started/">Getting Started</a> &nbsp;·&nbsp;
  <a href="https://maxl94.github.io/yaai/server-setup/">Server Setup</a> &nbsp;·&nbsp;
  <a href="https://maxl94.github.io/yaai/deployment/">Deployment</a>
</p>

---

![Models Overview](https://raw.githubusercontent.com/Maxl94/yaai/main/docs/screenshots/models.jpeg)

## Why This Exists

Most ML monitoring tools make you configure dashboards by hand, wire up custom pipelines, and learn their specific way of thinking before you see any value. YAAI takes a different approach:

- **REST-based** — send JSON, done
- **Auto-everything** — dashboards, drift detection, comparisons generated from your schema
- **Zero config** — no YAML files, no property mappings, no pipeline integrations

Define your fields once (or let YAAI guess them), send data, get insights.

## Quick Start

```bash
git clone https://github.com/Maxl94/yaai.git
cd yaai
cp .env.example .env
docker compose up -d
```

Open **http://localhost:8000** — the server and frontend are ready.

Default login: `admin` / check the server logs for the generated password.

For detailed setup instructions, see the **[Server Setup Guide](https://maxl94.github.io/yaai/server-setup/)** (development) or the **[Deployment Guide](https://maxl94.github.io/yaai/deployment/)** (production).

## Installation

```bash
pip install yaai-monitoring              # SDK only (httpx + pydantic)
pip install "yaai-monitoring[server]"    # Full server
pip install "yaai-monitoring[server,gcp]" # Server + Google Cloud support
```

## SDK Example

```python
import asyncio
from yaai import YaaiClient
from yaai.schemas.model import SchemaFieldCreate

async def main():
    async with YaaiClient("http://localhost:8000/api/v1", api_key="yaam_...") as client:
        model = await client.create_model("fraud-detector")
        version = await client.create_model_version(
            model_id=model.id,
            version="v1.0",
            schema_fields=[
                SchemaFieldCreate(field_name="amount", direction="input", data_type="numerical"),
                SchemaFieldCreate(field_name="country", direction="input", data_type="categorical"),
                SchemaFieldCreate(field_name="is_fraud", direction="output", data_type="categorical"),
            ],
        )
        await client.add_inferences(
            model_version_id=version.id,
            records=[
                {"inputs": {"amount": 42.0, "country": "US"}, "outputs": {"is_fraud": "false"}},
                {"inputs": {"amount": 9001.0, "country": "NG"}, "outputs": {"is_fraud": "true"}},
            ],
        )

asyncio.run(main())
```

## Screenshots

### Dashboard
![Dashboard](https://raw.githubusercontent.com/Maxl94/yaai/main/docs/screenshots/model_version_dashboard.jpeg)

### Drift Detection
![Drift](https://raw.githubusercontent.com/Maxl94/yaai/main/docs/screenshots/drift_dashboard.jpeg)

## Features

- **Schema-driven** — define fields once, everything else is automatic
- **Drift detection** — PSI, KS test, Chi-squared, Jensen-Shannon divergence
- **Scheduled jobs** — cron-based checks with configurable windows
- **Auto-dashboards** — per-feature distribution charts
- **Time comparisons** — compare any two periods side by side
- **Auth** — local accounts, Google OAuth, API keys, Google service accounts
- **Cloud SQL support** — IAM-authenticated connections to Google Cloud SQL

## Documentation

Full documentation is available at **[maxl94.github.io/yaai](https://maxl94.github.io/yaai/)**.

- [Getting Started](https://maxl94.github.io/yaai/getting-started/) — from zero to dashboards in five minutes
- [Server Setup](https://maxl94.github.io/yaai/server-setup/) — local development with PostgreSQL, env vars, authentication
- [Deployment](https://maxl94.github.io/yaai/deployment/) — Docker Compose, pip install, Google Cloud SQL
- [Core Concepts](https://maxl94.github.io/yaai/concepts/) — models, versions, schemas, drift detection
- [Drift Detection Guide](https://maxl94.github.io/yaai/drift-guide/) — deep dive into the four drift metrics
- [REST API Reference](https://maxl94.github.io/yaai/reference/api/) — full OpenAPI spec
- [Python SDK Reference](https://maxl94.github.io/yaai/reference/sdk/) — async client docs

## Development

```bash
# Start database
docker compose up db -d

# Install dependencies
uv sync
cd frontend && npm ci && cd ..

# Start backend (hot-reload)
cp .env.example .env
uv run uvicorn yaai.server.main:app --reload --reload-dir yaai --host 0.0.0.0 --port 8000

# Start frontend (separate terminal, hot-reload)
cd frontend && npm run dev
```

```bash
# Run tests
uv run pytest
cd frontend && npm run type-check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for commit conventions and PR guidelines.

## License

[Elastic License 2.0](LICENSE)
