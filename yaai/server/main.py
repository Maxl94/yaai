import logging
import os
import secrets as _secrets
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from yaai.server import database
from yaai.server.auth.config import load_auth_config, validate_auth_config
from yaai.server.auth.dependencies import get_auth_config, set_auth_config
from yaai.server.auth.oauth import setup_oauth
from yaai.server.auth.passwords import hash_password
from yaai.server.config import settings
from yaai.server.models import auth as _auth_models  # noqa: F401
from yaai.server.models.auth import AuthProvider, User, UserRole
from yaai.server.rate_limit import limiter
from yaai.server.routers import auth, dashboard, inferences, jobs, models, schema
from yaai.server.scheduler import load_active_jobs, scheduler

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
_SERVER_DIR = Path(__file__).resolve().parent


def _apply_migrations(sync_creator=None) -> None:
    """Run Alembic migrations up to head.

    Called on startup to ensure the database schema is always up to date.
    Disable by setting AUTO_MIGRATE=false.

    Args:
        sync_creator: Optional sync callable for Cloud SQL Connector.
                      When provided, creates a pg8000 engine with this creator.
    """
    alembic_cfg = AlembicConfig(str(_SERVER_DIR / "alembic.ini"))
    if sync_creator is not None:
        from sqlalchemy import create_engine

        sync_engine = create_engine("postgresql+pg8000://", creator=sync_creator)
        with sync_engine.begin() as connection:
            alembic_cfg.attributes["connection"] = connection
            command.upgrade(alembic_cfg, "head")
    else:
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url_sync)
        command.upgrade(alembic_cfg, "head")


async def _bootstrap_admin() -> None:
    """Create a default admin user if the users table is empty.

    Generates a random password and logs it once. The admin should change
    it immediately after first login.
    """
    async with database.async_session() as db:
        result = await db.execute(select(User).limit(1))
        if result.scalars().first() is not None:
            return

        password = _secrets.token_urlsafe(16)
        admin = User(
            username="admin",
            hashed_password=hash_password(password),
            role=UserRole.OWNER,
            auth_provider=AuthProvider.LOCAL,
        )
        db.add(admin)
        await db.commit()
        logger.info(
            "Created default admin account — username: admin, password: %s  "
            "(change this immediately after first login)",
            password,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    cloud_sql = None

    # Initialize Cloud SQL connector if configured
    if settings.cloud_sql_instance:
        from yaai.server.cloud_sql import CloudSQLConnector

        cloud_sql = CloudSQLConnector()
        await cloud_sql.startup()
        database.init_engine(async_creator=cloud_sql.async_creator)

    # Load auth configuration (skip if already pre-set, e.g. by tests)
    from yaai.server.auth.dependencies import _auth_config as _existing

    if _existing is None:
        auth_config = load_auth_config()
        auth_config = validate_auth_config(auth_config)
        set_auth_config(auth_config)
    else:
        auth_config = _existing

    if auth_config.oauth.google.enabled:
        setup_oauth(auth_config)

    # Apply database migrations on startup (disable with AUTO_MIGRATE=false)
    if os.environ.get("AUTO_MIGRATE", "true").lower() in ("true", "1", "yes"):
        _apply_migrations(sync_creator=cloud_sql.sync_creator if cloud_sql else None)
    else:
        logger.info("AUTO_MIGRATE is disabled — skipping automatic migrations.")

    # Create default admin account if no users exist (local auth only)
    if auth_config.enabled and auth_config.local_enabled:
        await _bootstrap_admin()

    # Start job scheduler
    async with database.async_session() as db:
        await load_active_jobs(db)
    scheduler.start()

    yield

    scheduler.shutdown(wait=False)

    if cloud_sql:
        await cloud_sql.shutdown()


app = FastAPI(
    title="YAAI Monitoring",
    description="Yet Another AI Monitoring — schema-driven ML model monitoring platform",
    version="0.1.0",
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
_session_secret = os.environ.get("SESSION_SECRET", "")
if not _session_secret or _session_secret == "dev-session-secret-change-me":
    _session_secret = _secrets.token_urlsafe(32)
    logger.warning(
        "SESSION_SECRET not configured — generated ephemeral secret. "
        "OAuth state will NOT survive restarts. Set SESSION_SECRET for persistence."
    )
app.add_middleware(SessionMiddleware, secret_key=_session_secret)

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
        # Prevent path traversal attacks
        file_path = (STATIC_DIR / full_path).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())):
            return FileResponse(STATIC_DIR / "index.html")
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
