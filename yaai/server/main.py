import importlib.metadata
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from yaai.server import database, startup
from yaai.server.admin_bootstrap import deliver_generated_password, resolve_admin_password
from yaai.server.auth.config import load_auth_config, validate_auth_config
from yaai.server.auth.dependencies import set_auth_config
from yaai.server.auth.oauth import setup_oauth
from yaai.server.auth.passwords import hash_password
from yaai.server.config import api_docs_enabled, resolve_session_secret, settings
from yaai.server.models import auth as _auth_models  # noqa: F401
from yaai.server.models import project as _project_models  # noqa: F401
from yaai.server.models.auth import AuthProvider, User, UserRole
from yaai.server.rate_limit import limiter
from yaai.server.routers import auth, dashboard, inferences, jobs, models, projects, schema
from yaai.server.scheduler import scheduler_enabled
from yaai.server.security_headers import SecurityHeadersMiddleware, security_headers_enabled
from yaai.server.spa import mount_spa

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


async def _bootstrap_admin() -> None:
    """Create a default admin user if the users table is empty.

    Uses BOOTSTRAP_ADMIN_PASSWORD if set, otherwise generates a random password and
    stores it in a new 0600 file (never logged; stderr only as a one-time fallback).
    The admin should change it after first login.
    """
    async with database.async_session() as db:
        result = await db.execute(select(User).limit(1))
        if result.scalars().first() is not None:
            return

        # Deliver the password before creating the user so a failure never leaves an admin with an unknown password
        password, generated = resolve_admin_password()
        admin = User(
            username="admin",
            hashed_password=hash_password(password),
            role=UserRole.OWNER,
            auth_provider=AuthProvider.LOCAL,
        )
        password_file = deliver_generated_password(password) if generated else None
        db.add(admin)
        try:
            await db.commit()
        except Exception:
            if password_file is not None:
                password_file.unlink(missing_ok=True)
            raise
        if not generated:
            logger.info("Created default admin account (username: admin) with BOOTSTRAP_ADMIN_PASSWORD.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cloud_sql = await startup.init_database()

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

    # Start job scheduler (SCHEDULER_ENABLED=false for API-only instances)
    if scheduler_enabled():
        await startup.start_scheduler()
    else:
        logger.info("SCHEDULER_ENABLED is false — scheduled jobs will not run on this instance.")
    logger.info("Startup complete.")

    yield

    await startup.shutdown(cloud_sql)


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
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# Session middleware required for OAuth state (authlib uses it)
_session_secret = resolve_session_secret()
app.add_middleware(SessionMiddleware, secret_key=_session_secret)

# Added last so it wraps every other middleware and response
if security_headers_enabled():
    app.add_middleware(SecurityHeadersMiddleware, base_url=settings.base_url, docs_enabled=_docs_enabled)

# Routers
API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(models.router, prefix=API_PREFIX)
app.include_router(projects.router, prefix=API_PREFIX)
app.include_router(inferences.router, prefix=API_PREFIX)
app.include_router(jobs.router, prefix=API_PREFIX)
app.include_router(dashboard.router, prefix=API_PREFIX)
app.include_router(schema.router, prefix=API_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok"}


# Serve frontend static files (built by Vite, copied into yaai/server/static in Docker)
if STATIC_DIR.is_dir():
    mount_spa(app, STATIC_DIR, API_PREFIX)
