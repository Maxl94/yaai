# Server Setup

This guide walks you through setting up the YAAI server for local development. For production deployments, see [Deployment](deployment.md).

## Prerequisites

- **Docker** (for PostgreSQL, or bring your own)
- **Python 3.12+** and [uv](https://docs.astral.sh/uv/) (recommended) or pip
- **Node.js 20+** (only for frontend development)

## 1. Install the server

=== "uv"

    ```bash
    uv add "yaai-monitoring[server]"
    ```

=== "pip"

    ```bash
    pip install "yaai-monitoring[server]"
    ```

This pulls in FastAPI, SQLAlchemy, scikit-learn, and all backend dependencies.

## 2. Start PostgreSQL

The simplest option is Docker Compose. Clone the repo and start only the database:

```bash
git clone https://github.com/Maxl94/yaai.git
cd yaai
docker compose up db -d
```

This starts PostgreSQL 16 on port **5431** (not the default 5432, to avoid conflicts with any local PostgreSQL).

> [!NOTE]
> **Bring your own PostgreSQL** — If you already have a PostgreSQL instance, skip this step and configure `DATABASE_URL` to point to it.

## 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and set the values below. The defaults work for local development with the Docker Compose database.

### Required variables

| Variable | Description | Example |
|---|---|---|
| `BASE_URL` | Public URL of your server (used for CORS, OAuth redirects, SA audience) | `http://localhost:8000` |
| `DATABASE_URL` | Async connection string (asyncpg driver). Sync URL is derived automatically. | `postgresql+asyncpg://aimon:changeme@localhost:5431/aimonitoring` |

> [!NOTE]
> The defaults in `.env.example` are fine for local development. For production, see the [Deployment](deployment.md) guide.

### Optional variables

| Variable | Default | Description |
|---|---|---|
| `AUTH_JWT_SECRET` | *(auto-generated)* | Secret for signing JWT tokens. If not set, an ephemeral secret is generated on startup (sessions won't survive restarts). Generate with `openssl rand -base64 32`. |
| `SESSION_SECRET` | *(auto-generated)* | Secret for session middleware (OAuth state). Same behavior as JWT secret. |
| `CORS_ALLOWED_ORIGINS` | *(derived from BASE_URL)* | Comma-separated allowed CORS origins. Only set if you need origins different from BASE_URL. |
| `AUTO_MIGRATE` | `true` | Run Alembic migrations automatically on startup |
| `ENVIRONMENT` | `development` | Set to `production` to enforce secure credentials |
| `AUTH_ENABLED` | `true` | Master auth switch |
| `AUTH_LOCAL_ALLOW_REGISTRATION` | `false` | Allow public user registration |
| `AUTH_SERVICE_ACCOUNTS_API_KEYS_ENABLED` | `true` | Enable API key authentication |

> [!TIP]
> **Simplified configuration** — Several settings are now auto-derived to reduce configuration burden:
>
> - **Sync DB URL** — derived from `DATABASE_URL` (strips `+asyncpg` driver)
> - **Local auth** — enabled automatically unless Google OAuth is configured
> - **CORS origins** — defaults to `BASE_URL`
> - **SA audience** — defaults to `BASE_URL`
> - **Admin password** — auto-generated and logged on first startup
> - **JWT algorithm** — hardcoded to HS256 (not configurable)
> - **Token expiry** — hardcoded to 60 min (access) / 30 days (refresh)

## 4. Start the server

```bash
uv run uvicorn yaai.server.main:app --reload --reload-dir yaai --host 0.0.0.0 --port 8000
```

On first startup, the server will:

1. **Run database migrations** automatically (unless `AUTO_MIGRATE=false`)
2. **Create a default admin account** with the username `admin` and a randomly generated password (check the server logs for the password)

Open **http://localhost:8000** -- you should see the login screen.

API docs are available at **http://localhost:8000/docs** (Swagger UI).

## 5. Start the frontend (development only)

For local development with frontend hot-reload, start the Vue dev server in a separate terminal:

```bash
cd frontend && npm ci && npm run dev
```

The frontend runs on **http://localhost:3000** and proxies `/api` requests to the backend on port 8000.

> [!TIP]
> If you started the server via `docker compose up -d`, the frontend is already bundled and served from port 8000. You only need a separate frontend process for development with hot-reload.

## 6. Authentication

Out of the box, the server uses **local authentication** (username + password) with **API key auth** enabled for service accounts.

### Default admin account

On first startup (when no users exist), the server creates an admin account:

- **Username**: `admin`
- **Password**: randomly generated -- check the server logs for the password

Change the password immediately after first login.

### API keys

API keys are the primary way for SDK clients and services to authenticate. After logging in as admin:

1. Create a **service account** via the API
2. Generate an **API key** for that service account
3. Use the key in requests: `X-API-Key: yaam_...`

### Google OAuth (optional)

To enable Google OAuth for browser-based login, set these variables:

```bash
AUTH_OAUTH_GOOGLE_ENABLED=true
AUTH_OAUTH_GOOGLE_CLIENT_ID=your-client-id
AUTH_OAUTH_GOOGLE_CLIENT_SECRET=your-client-secret
AUTH_OAUTH_GOOGLE_ALLOWED_DOMAINS=example.com,mycompany.com
AUTH_OAUTH_GOOGLE_AUTO_CREATE_USERS=true
AUTH_OAUTH_GOOGLE_OWNER_EMAILS=admin@example.com
AUTH_OAUTH_GOOGLE_VIEWER_EMAILS=user@example.com
```

`AUTH_OAUTH_GOOGLE_OWNER_EMAILS` and `AUTH_OAUTH_GOOGLE_VIEWER_EMAILS` are optional explicit overrides.
Users from `AUTH_OAUTH_GOOGLE_ALLOWED_DOMAINS` who are not in those lists are assigned
`AUTH_OAUTH_GOOGLE_DEFAULT_ROLE` (defaults to `viewer`).

> [!IMPORTANT]
> When Google OAuth is enabled, local username/password authentication is automatically disabled. Users must sign in with their Google account.

Configure the OAuth redirect URI in Google Cloud Console to:

```
{BASE_URL}/api/v1/auth/oauth/google/callback
```

For local development this is `http://localhost:8000/api/v1/auth/oauth/google/callback`.

> [!NOTE]
> Google OAuth only works when the frontend and backend share the same origin (same host and port). This works with Docker Compose or the [hybrid approach](#hybrid-build-frontend-locally-serve-from-backend) below, but **not** with separate dev servers (frontend on :3000, backend on :8000).

### Hybrid: build frontend locally, serve from backend

If you want Google OAuth without Docker but don't need frontend hot-reload:

```bash
cd frontend && npm run build-only && cd ..
cp -r frontend/dist/* yaai/server/static/
uv run uvicorn yaai.server.main:app --reload --reload-dir yaai --host 0.0.0.0 --port 8000
```

## 7. Load demo data

Two scripts are included to populate the server with sample models, inferences, and drift data:

```bash
# Via REST API
uv run scripts/generate_demo_data.py --drop-all --mode full --dataset all

# Via Python SDK
API_KEY=your_key uv run scripts/generate_demo_data_sdk.py --drop-all --mode full --dataset all
```

## Troubleshooting

**"Address already in use" on port 8000**
: Another process is using port 8000 -- most likely the Docker backend container. Make sure you started only `docker compose up db -d` (not the full stack). Check with `lsof -i :8000`.

**"FATAL: Database URL contains default credentials"**
: You're running with `ENVIRONMENT=production` but haven't changed the default `changeme` password. Set `DATABASE_URL` with secure credentials.

**Migrations fail on startup**
: Check that PostgreSQL is running and `DATABASE_URL` is correct. You can disable auto-migration with `AUTO_MIGRATE=false` and run manually: `uv run alembic upgrade head`.
