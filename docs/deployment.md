# Deployment

This guide covers deploying YAAI to production. No repo clone needed -- everything installs from PyPI.

> [!IMPORTANT]
> This page is for **production deployments**. For local development, see [Server Setup](server-setup.md).

## Production checklist

Before going live, make sure you've set these:

- **`ENVIRONMENT=production`** -- the server refuses to start with default credentials in production mode
- **`BASE_URL`** -- your public URL (e.g. `https://yaai.mycompany.com`). Used for CORS, OAuth redirects, and service account audience.
- **`DATABASE_URL`** -- point to a managed PostgreSQL instance with strong credentials (not `changeme`)
- **`AUTH_JWT_SECRET`** and **`SESSION_SECRET`** -- optional but recommended. If not set, the server auto-generates ephemeral secrets on startup (sessions won't survive restarts). Generate with `openssl rand -base64 32`.

## Docker Compose

The recommended way to deploy. Create these two files -- no repo clone required.

### Dockerfile

```dockerfile
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN pip install "yaai-monitoring[server]"

EXPOSE 8000

CMD ["uvicorn", "yaai.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

> [!TIP]
> For Google Cloud SQL support, use `"yaai-monitoring[server,gcp]"` instead.

### docker-compose.yml

=== "Local auth (default)"

    Username + password login with API key auth for service accounts. An admin account is created automatically on first startup -- check the server logs for the generated password.

    ```yaml
    services:
      db:
        image: postgres:16-alpine
        environment:
          POSTGRES_USER: aimon
          POSTGRES_PASSWORD: change-me-in-production
          POSTGRES_DB: aimonitoring
        volumes:
          - pgdata:/var/lib/postgresql/data
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U aimon -d aimonitoring"]
          interval: 5s
          timeout: 3s
          retries: 5

      yaai:
        build: .
        ports:
          - "8000:8000"
        environment:
          BASE_URL: http://localhost:8000
          DATABASE_URL: postgresql+asyncpg://aimon:change-me-in-production@db:5432/aimonitoring
          ENVIRONMENT: production
          AUTH_ENABLED: "true"
          # AUTH_JWT_SECRET: <generate with: openssl rand -base64 32>
          # SESSION_SECRET: <generate with: openssl rand -base64 32>
        depends_on:
          db:
            condition: service_healthy

    volumes:
      pgdata:
    ```

=== "Google OAuth"

    Browser users sign in with Google. Local auth is automatically disabled when Google OAuth is enabled. API key auth still works for service accounts.

    > [!NOTE]
    > Google OAuth requires the frontend and backend to share the same origin (same host and port). Docker Compose handles this -- the server serves both the API and the frontend on port 8000.

    ```yaml
    services:
      db:
        image: postgres:16-alpine
        environment:
          POSTGRES_USER: aimon
          POSTGRES_PASSWORD: change-me-in-production
          POSTGRES_DB: aimonitoring
        volumes:
          - pgdata:/var/lib/postgresql/data
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U aimon -d aimonitoring"]
          interval: 5s
          timeout: 3s
          retries: 5

      yaai:
        build: .
        ports:
          - "8000:8000"
        environment:
          BASE_URL: https://yaai.mycompany.com
          DATABASE_URL: postgresql+asyncpg://aimon:change-me-in-production@db:5432/aimonitoring
          ENVIRONMENT: production
          AUTH_ENABLED: "true"
          # AUTH_JWT_SECRET: <generate with: openssl rand -base64 32>
          # SESSION_SECRET: <generate with: openssl rand -base64 32>

          # Google OAuth
          AUTH_OAUTH_GOOGLE_ENABLED: "true"
          AUTH_OAUTH_GOOGLE_CLIENT_ID: your-client-id
          AUTH_OAUTH_GOOGLE_CLIENT_SECRET: your-client-secret
          AUTH_OAUTH_GOOGLE_ALLOWED_DOMAINS: mycompany.com
          AUTH_OAUTH_GOOGLE_AUTO_CREATE_USERS: "true"
          AUTH_OAUTH_GOOGLE_OWNER_EMAILS: admin@mycompany.com
          # AUTH_OAUTH_GOOGLE_VIEWER_EMAILS: analyst@mycompany.com
        depends_on:
          db:
            condition: service_healthy

    volumes:
      pgdata:
    ```

    Set the OAuth redirect URI in Google Cloud Console to:

    ```
    {BASE_URL}/api/v1/auth/oauth/google/callback
    ```

### Start the server

```bash
docker compose up -d
```

Open your `BASE_URL` -- you should see the login screen. Migrations run automatically on startup.

> [!TIP]
> **Already cloned the repo?** You can also deploy directly with the included `docker-compose.yml` and `Dockerfile.dev`. Copy `.env.example` to `.env`, set your values, and run `docker compose up -d`. The repo's Dockerfile builds the frontend from source and includes a healthcheck.

## Without Docker

Install the server package and run uvicorn directly. You need Python 3.12+ and a PostgreSQL instance.

```bash
pip install "yaai-monitoring[server]"
```

Set environment variables (via `.env` file, shell exports, or your process manager):

```bash
export BASE_URL=https://yaai.mycompany.com
export DATABASE_URL=postgresql+asyncpg://user:password@your-db-host:5432/aimonitoring
export ENVIRONMENT=production
export AUTH_ENABLED=true
```

Start the server:

```bash
uvicorn yaai.server.main:app --host 0.0.0.0 --port 8000
```

The server runs migrations automatically, creates the admin account, and serves both the API and the frontend.

## Google Cloud SQL

If your PostgreSQL runs on Google Cloud SQL, YAAI can connect using the **Cloud SQL Python Connector** with IAM authentication -- no IP allow-lists, SSL certificates, or Auth Proxy needed.

### Install the GCP extras

```bash
pip install "yaai-monitoring[server,gcp]"
```

This adds the Cloud SQL Connector, `pg8000` (for migrations), and `google-auth`.

### Configure connection

Set these environment variables **instead of** `DATABASE_URL`:

```bash
CLOUD_SQL_INSTANCE=my-project:us-central1:yaai-db
CLOUD_SQL_USER=yaai-server@my-project.iam.gserviceaccount.com
CLOUD_SQL_DATABASE=aimonitoring
CLOUD_SQL_IAM_AUTH=true
CLOUD_SQL_IP_TYPE=public    # public, private, or psc
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `CLOUD_SQL_INSTANCE` | Yes | -- | Instance connection name (`project:region:instance`) |
| `CLOUD_SQL_USER` | Yes | -- | IAM user email (full service account email) |
| `CLOUD_SQL_DATABASE` | No | `aimonitoring` | Database name |
| `CLOUD_SQL_IAM_AUTH` | No | `true` | Use IAM authentication (set `false` for password auth) |
| `CLOUD_SQL_IP_TYPE` | No | `public` | Connection type: `public`, `private`, or `psc` |

When `CLOUD_SQL_INSTANCE` is set, the connector handles all database connections automatically. `DATABASE_URL` is ignored.

### Google service account auth for SDK clients

SDK clients on GCP workloads can authenticate using Google Application Default Credentials instead of API keys:

```bash
AUTH_SERVICE_ACCOUNTS_GOOGLE_ENABLED=true
AUTH_SERVICE_ACCOUNTS_GOOGLE_ALLOWED_EMAILS=ml-pipeline@my-project.iam.gserviceaccount.com
# Audience defaults to BASE_URL -- only set if you need a different value
# AUTH_SERVICE_ACCOUNTS_GOOGLE_AUDIENCE=https://yaai.mycompany.com
```

```python
from yaai import YaaiClient

# No api_key → automatically uses Google ADC
async with YaaiClient("https://yaai.mycompany.com/api/v1") as client:
    model = await client.create_model("my-model")
```

> [!TIP]
> SDK clients using Google SA auth need the `gcp` extra: `pip install "yaai-monitoring[gcp]"`. Clients using API keys only need the base package.

## Troubleshooting

**Server refuses to start in production mode**
: You're running with `ENVIRONMENT=production` but haven't changed the default `changeme` password in `DATABASE_URL`. Use strong credentials.

**Migrations fail on startup**
: Check that PostgreSQL is running and `DATABASE_URL` is correct. Disable auto-migration with `AUTO_MIGRATE=false` and run manually: `alembic upgrade head`.

**Google OAuth login redirects fail**
: Verify `BASE_URL` matches the origin users access in their browser, and that the OAuth redirect URI in Google Cloud Console matches `{BASE_URL}/api/v1/auth/oauth/google/callback`.

**Cloud SQL connection fails**
: Check that the service account has both `Cloud SQL Client` and `Cloud SQL Instance User` roles. Verify the IAM database user was created with `gcloud sql users list --instance=yaai-db`.

**"Could not automatically determine credentials"**
: No GCP credentials found. Run `gcloud auth application-default login` locally, or attach a service account to your Cloud Run / GKE workload.
