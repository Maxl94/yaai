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

      migrate:
        build: .
        command: ["python", "-m", "yaai.server.migrate"]
        environment:
          DATABASE_URL: postgresql+asyncpg://aimon:change-me-in-production@db:5432/aimonitoring
        restart: "no"
        depends_on:
          db:
            condition: service_healthy

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
          migrate:
            condition: service_completed_successfully

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

      migrate:
        build: .
        command: ["python", "-m", "yaai.server.migrate"]
        environment:
          DATABASE_URL: postgresql+asyncpg://aimon:change-me-in-production@db:5432/aimonitoring
        restart: "no"
        depends_on:
          db:
            condition: service_healthy

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

          # Google service account auth (SDK clients)
          AUTH_SERVICE_ACCOUNTS_GOOGLE_ENABLED: "true"
          AUTH_SERVICE_ACCOUNTS_GOOGLE_ALLOWED_EMAILS: ml-pipeline@my-project.iam.gserviceaccount.com
          # AUTH_SERVICE_ACCOUNTS_GOOGLE_AUDIENCE: https://yaai.mycompany.com  # defaults to BASE_URL
        depends_on:
          db:
            condition: service_healthy
          migrate:
            condition: service_completed_successfully

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

Open your `BASE_URL` -- you should see the login screen. The one-shot `migrate` service applies pending database migrations before the server starts; the server itself never migrates and refuses to start if the schema is behind.

> [!TIP]
> **Already cloned the repo?** You can also deploy directly with the included `docker-compose.yml` and `Dockerfile.dev`. Copy `.env.example` to `.env`, set your values, and run `docker compose up -d`. The repo's Dockerfile builds the frontend from source and includes a healthcheck.

## Without Docker

Install the server package and run uvicorn directly. You need Python 3.11+ and a PostgreSQL instance.

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

Apply database migrations (on first install and after every upgrade), then start the server:

```bash
python -m yaai.server.migrate
uvicorn yaai.server.main:app --host 0.0.0.0 --port 8000
```

The server checks on startup that the schema is up to date, creates the admin account, and serves both the API and the frontend.

## Google Cloud SQL

If your PostgreSQL runs on Google Cloud SQL, YAAI can connect using the **Cloud SQL Python Connector** with IAM authentication -- no IP allow-lists, SSL certificates, or Auth Proxy needed.

### Install the GCP extras

```bash
pip install "yaai-monitoring[server,gcp]"
```

This adds the Cloud SQL Connector, `pg8000` (for migrations and the startup schema check), and `google-auth`.

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

### Run migrations as a Cloud Run Job

The server never migrates on startup, so on GCP run migrations as a **Cloud Run Job** that uses the same image as the service and executes `python -m yaai.server.migrate`. The job connects through the Cloud SQL Connector exactly like the server (same `CLOUD_SQL_*` variables), so no Auth Proxy is needed.

Run the job with the **same service account and database user as the service**. PostgreSQL tables are owned by the user that creates them, so a different migration user would either lock the server out of new tables or be unable to alter the existing ones. If you want a dedicated migration service account anyway, you must set up the roles yourself (e.g. make the migration user a member of the server's role or transfer ownership, and use `ALTER DEFAULT PRIVILEGES` for new objects).

```bash
# One-time setup: job with the same service account and settings as the service
gcloud run jobs create yaai-migrate \
  --image europe-west1-docker.pkg.dev/my-project/yaai/yaai:TAG \
  --command python --args=-m,yaai.server.migrate \
  --service-account yaai-server@my-project.iam.gserviceaccount.com \
  --set-env-vars CLOUD_SQL_INSTANCE=my-project:us-central1:yaai-db,CLOUD_SQL_USER=yaai-server@my-project.iam.gserviceaccount.com,CLOUD_SQL_DATABASE=aimonitoring \
  --region us-central1
```

> [!NOTE]
> With `CLOUD_SQL_IP_TYPE=private` or `psc` the job needs the same network access as the service: configure Direct VPC egress (`--network`/`--subnet`) or a Serverless VPC connector (`--vpc-connector`) on the job as well. With `public` no extra networking is required.

In your CD pipeline, update and run the job **before** deploying the new service revision. `--wait` makes the step fail if the migration fails, so the old revision keeps serving. Example GitHub Actions steps:

```yaml
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ vars.WIF_PROVIDER }}
    service_account: ${{ vars.DEPLOY_SERVICE_ACCOUNT }}
- uses: google-github-actions/setup-gcloud@v2
- name: Run database migrations
  run: |
    gcloud run jobs update yaai-migrate --image "$IMAGE" --region us-central1
    gcloud run jobs execute yaai-migrate --region us-central1 --wait
- name: Deploy service
  run: gcloud run deploy yaai --image "$IMAGE" --region us-central1
```

#### Rollbacks and backward-compatible migrations

On startup the server fails fast if the database is empty or **behind** the application. If the database is **ahead** (it was already migrated by a newer version, e.g. while the old revision still serves traffic or after a traffic rollback), the server only logs a warning and keeps starting. This means migrations must be backward compatible with the previous application version (expand/contract): add columns/tables first, and remove or rename them only in a later release once no older version uses them. `python -m yaai.server.migrate` refuses to run with an older image against a newer database and exits with a clear error.

A Cloud Run Job is preferred over a Cloud Function: it reuses the already built application image (including Alembic and the migration files), so there is no separate packaging or dependency set to maintain, and it can run longer than function timeouts allow.

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

**"Database schema is not up to date" on startup**
: The server does not apply migrations automatically. Run `python -m yaai.server.migrate` (Docker Compose: make sure the `migrate` service is defined and completed; Cloud Run: execute the migration job) and start the server again.

**Migrations fail**
: Check that PostgreSQL is running and `DATABASE_URL` (or the `CLOUD_SQL_*` variables) is correct.

**Google OAuth login redirects fail**
: Verify `BASE_URL` matches the origin users access in their browser, and that the OAuth redirect URI in Google Cloud Console matches `{BASE_URL}/api/v1/auth/oauth/google/callback`.

**Cloud SQL connection fails**
: Check that the service account has both `Cloud SQL Client` and `Cloud SQL Instance User` roles. Verify the IAM database user was created with `gcloud sql users list --instance=yaai-db`.

**"Could not automatically determine credentials"**
: No GCP credentials found. Run `gcloud auth application-default login` locally, or attach a service account to your Cloud Run / GKE workload.
