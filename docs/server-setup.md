# Server Setup

This guide walks you through setting up the YAAI server for local development. For production deployments, see [Deployment](deployment.md).

## Prerequisites

- **Docker** (for PostgreSQL, or bring your own)
- **Python 3.11+** and [uv](https://docs.astral.sh/uv/) (recommended) or pip
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
| `AUTH_JWT_SECRET` | *(auto-generated in development)* | Secret for signing JWT tokens. In development an ephemeral secret is generated if unset (sessions won't survive restarts). **Required when `ENVIRONMENT=production`** -- the server refuses to start without it. Generate with `openssl rand -base64 32`. |
| `SESSION_SECRET` | *(auto-generated in development)* | Secret for session middleware (OAuth state). Same behavior as the JWT secret, including the production requirement. |
| `BOOTSTRAP_ADMIN_PASSWORD` | *(generated)* | Initial password of the `admin` account (min. 12 characters). If unset, one is generated and written to `BOOTSTRAP_ADMIN_PASSWORD_FILE`. |
| `BOOTSTRAP_ADMIN_PASSWORD_FILE` | `./admin-initial-password.txt` | Where the generated initial admin password is stored (new file, mode `0600`, never overwritten). |
| `API_DOCS_ENABLED` | `true` (development) / `false` (production) | Expose Swagger UI (`/docs`), ReDoc (`/redoc`) and `/openapi.json`. |
| `SECURITY_HEADERS_ENABLED` | `true` | Add security headers (CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, HSTS over HTTPS). |
| `RATE_LIMIT_ENABLED` | `true` | Enable rate limiting. |
| `RATE_LIMIT_TRUSTED_PROXY_HOPS` | `0` | Number of trusted reverse proxies in front of the server. When > 0 the client IP is read from `X-Forwarded-For` (N-th entry from the right). Set to `1` on Cloud Run accessed directly, typically `2` behind an external HTTPS load balancer; otherwise all users share the proxy IP. |
| `RATE_LIMIT_STORAGE_URI` | `memory://` | Rate limit counter storage (e.g. `redis://host:6379`). The default is per instance; see [Running multiple instances](deployment.md#running-multiple-instances). |
| `SCHEDULER_ENABLED` | `true` | Run the drift job scheduler in this instance. Use `false` for API-only instances. |
| `SCHEDULER_SYNC_INTERVAL_SECONDS` | `60` | How often the scheduler reloads active jobs from the database (picks up job changes made on other instances). |
| `CORS_ALLOWED_ORIGINS` | *(derived from BASE_URL)* | Comma-separated allowed CORS origins. Only set if you need origins different from BASE_URL. |
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
> - **Admin password** — auto-generated and written to a 0600 file on first startup (never logged)
> - **JWT algorithm** — hardcoded to HS256 (not configurable)
> - **Token expiry** — hardcoded to 60 min (access) / 30 days (refresh)

## 4. Run database migrations and start the server

The server does **not** migrate the database on startup. Apply the migrations first, and again after every upgrade:

```bash
uv run python -m yaai.server.migrate
```

Then start the server:

```bash
uv run uvicorn yaai.server.main:app --reload --reload-dir yaai --host 0.0.0.0 --port 8000
```

On startup, the server checks that the database schema is at the latest migration and exits with an error if it is not. On first startup, it will also:

1. **Create a default admin account** with the username `admin` and a randomly generated password (written to a file, see [Default admin account](#default-admin-account))

Open **http://localhost:8000** -- you should see the login screen.

API docs are available at **http://localhost:8000/docs** (Swagger UI) in development. They are disabled by default when `ENVIRONMENT=production` (see `API_DOCS_ENABLED`).

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
- **Password**: `BOOTSTRAP_ADMIN_PASSWORD` if set (at least 12 characters, otherwise the server refuses to start). Otherwise a random password is generated and written to `BOOTSTRAP_ADMIN_PASSWORD_FILE` (default `./admin-initial-password.txt` in the server's working directory) with permissions `0600`. The password is never written to the log; only the file path is. If the file cannot be created (not writable, or it already exists), the password is printed once to stderr with a warning -- in containers stderr is usually the log stream, so set `BOOTSTRAP_ADMIN_PASSWORD` or a writable `BOOTSTRAP_ADMIN_PASSWORD_FILE` instead. The admin account is only created after the password has been delivered.

Change the password immediately after first login and delete the file. With the repo's `docker compose`, the file lives in the container: `docker compose exec backend cat /home/appuser/admin-initial-password.txt`.

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

Existing Google users can also call the API directly (SDK or `gcloud auth print-identity-token`) with a Google ID token.
The token's audience must be the OAuth client ID or one of `AUTH_OAUTH_GOOGLE_TOKEN_AUDIENCES`, which defaults
to the public gcloud CLI and Application Default Credentials client IDs. Tokens issued to any other application are rejected.

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

**"Database schema is not up to date" on startup**
: The server no longer applies migrations automatically. Run `uv run python -m yaai.server.migrate` and start the server again.

**Migrations fail**
: Check that PostgreSQL is running and `DATABASE_URL` is correct.
