import asyncio
import importlib.metadata
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from yaai.server import database
from yaai.server.admin_bootstrap import deliver_generated_password, resolve_admin_password
from yaai.server.auth.config import load_auth_config, validate_auth_config
from yaai.server.auth.dependencies import set_auth_config
from yaai.server.auth.oauth import setup_oauth
from yaai.server.auth.passwords import hash_password
from yaai.server.config import api_docs_enabled, resolve_session_secret, settings
from yaai.server.migrate import SchemaNotUpToDateError, check_schema_up_to_date
from yaai.server.models import auth as _auth_models  # noqa: F401
from yaai.server.models.auth import AuthProvider, User, UserRole
from yaai.server.rate_limit import limiter
from yaai.server.routers import auth, dashboard, inferences, jobs, models, schema
from yaai.server.scheduler import load_active_jobs, scheduler, scheduler_enabled
from yaai.server.security_headers import SecurityHeadersMiddleware, security_headers_enabled
from yaai.server.spa import resolve_static_file

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


async def _bootstrap_admin() -> None:
    """Create a default admin user if the users table is empty.

    Uses BOOTSTRAP_ADMIN_PASSWORD if set, otherwise generates a random password and
    stores it in a 0600 file (never logged). The admin should change it after first login.
    """
    async with database.async_session() as db:
        result = await db.execute(select(User).limit(1))
        if result.scalars().first() is not None:
            return

        password, generated = resolve_admin_password()
        admin = User(
            username="admin",
            hashed_password=hash_password(password),
            role=UserRole.OWNER,
            auth_provider=AuthProvider.LOCAL,
        )
        db.add(admin)
        await db.commit()
        if generated:
            deliver_generated_password(password)
        else:
            logger.info("Created default admin account (username: admin) with BOOTSTRAP_ADMIN_PASSWORD.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cloud_sql = None

    # Migrations are never applied here; fail fast if the schema is behind
    try:
        await asyncio.to_thread(check_schema_up_to_date)
    except SchemaNotUpToDateError as exc:
        logger.error("%s", exc)
        raise

    # Initialize Cloud SQL async connector
    if settings.cloud_sql_instance:
        from yaai.server.cloud_sql import CloudSQLConnector  # noqa: PLC0415

        cloud_sql = CloudSQLConnector()
        await cloud_sql.startup()
        database.init_engine(async_creator=cloud_sql.async_creator)
        logger.info("Cloud SQL connector ready.")
    else:
        logger.info("Using DATABASE_URL (no Cloud SQL connector).")

    # Load auth configuration (skip if already pre-set, e.g. by tests)
    from yaai.server.auth.dependencies import _auth_config as _existing  # noqa: PLC0415

    if _existing is None:
        auth_config = load_auth_config()
        auth_config = validate_auth_config(auth_config)
        set_auth_config(auth_config)
    else:
        auth_config = _existing
    logger.info(
        "Auth config loaded (enabled=%s, oauth_google=%s).", auth_config.enabled, auth_config.oauth.google.enabled
    )

    if auth_config.oauth.google.enabled:
        setup_oauth(auth_config)
        logger.info("Google OAuth configured.")

    # Create default admin account if no users exist (local auth only)
    if auth_config.enabled and auth_config.local_enabled:
        await _bootstrap_admin()

    # Start job scheduler (disable with SCHEDULER_ENABLED=false on all but one instance)
    if scheduler_enabled():
        logger.info("Loading active jobs ...")
        async with database.async_session() as db:
            await load_active_jobs(db)
        scheduler.start()
    else:
        logger.info("SCHEDULER_ENABLED is false — scheduled jobs will not run on this instance.")
    logger.info("Startup complete.")

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)

    if cloud_sql:
        await cloud_sql.shutdown()


_docs_enabled = api_docs_enabled()
app = FastAPI(
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
    title="YAAI Monitoring",
    description="Yet Another AI Monitoring — schema-driven ML model monitoring platform",
    version=importlib.metadata.version("yaai-monitoring"),
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware — defaults to BASE_URL when CORS_ALLOWED_ORIGINS is not set
_cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _cors_env.strip():
    _cors_origins = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]
else:
    _cors_origins = [settings.base_url]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# Session middleware required for OAuth state (authlib uses it)
_session_secret = resolve_session_secret()
app.add_middleware(SessionMiddleware, secret_key=_session_secret)

# Added last so it wraps every other middleware and response
if security_headers_enabled():
    app.add_middleware(SecurityHeadersMiddleware, base_url=settings.base_url)

# Routers
API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(models.router, prefix=API_PREFIX)
app.include_router(inferences.router, prefix=API_PREFIX)
app.include_router(jobs.router, prefix=API_PREFIX)
app.include_router(dashboard.router, prefix=API_PREFIX)
app.include_router(schema.router, prefix=API_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Serve frontend static files (built by Vite, copied into yaai/server/static in Docker)
if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = resolve_static_file(STATIC_DIR, full_path)
        return FileResponse(file_path or STATIC_DIR / "index.html")
