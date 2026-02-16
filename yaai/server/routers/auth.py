"""Authentication and user management API endpoints."""

import secrets as _secrets
import uuid

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import RedirectResponse

from yaai.server.auth.config import AuthConfig
from yaai.server.auth.dependencies import (
    CurrentIdentity,
    get_auth_config,
    require_auth,
    require_owner,
)
from yaai.server.auth.jwt import decode_token
from yaai.server.auth.oauth import get_oauth
from yaai.server.auth.passwords import verify_password
from yaai.server.database import get_db
from yaai.server.models.auth import ModelAccess
from yaai.server.rate_limit import limiter
from yaai.server.schemas.auth import (
    AuthConfigResponse,
    LoginRequest,
    LogoutRequest,
    ModelAccessCreate,
    ModelAccessRead,
    PasswordChange,
    RefreshRequest,
    ServiceAccountCreate,
    ServiceAccountCreateResponse,
    ServiceAccountKeyInfo,
    ServiceAccountRead,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
from yaai.server.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

# Short-lived auth code -> tokens mapping (60 second TTL, max 1000 pending)
_oauth_code_store: TTLCache = TTLCache(maxsize=1000, ttl=60)


def _get_service(db: AsyncSession, config: AuthConfig) -> AuthService:
    return AuthService(db, config)


# Public endpoints


@router.get("/config")
async def get_config():
    """Return public auth configuration (what auth methods are available)."""
    config = get_auth_config()
    return {
        "data": AuthConfigResponse(
            enabled=config.enabled,
            local_enabled=config.local.enabled,
            google_oauth_enabled=config.oauth.google.enabled,
            allow_registration=config.local.allow_registration,
        )
    }


@router.post("/login")
@limiter.limit("20/minute")
async def login(request: Request, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate with username and password, returns JWT tokens."""
    config = get_auth_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Authentication is not enabled")
    if not config.local.enabled:
        raise HTTPException(status_code=400, detail="Local authentication is not enabled")

    svc = _get_service(db, config)
    user = await svc.authenticate_local(data.username, data.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    tokens = await svc.create_tokens(user)
    return {"data": TokenResponse(**tokens, user=UserRead.model_validate(user))}


@router.post("/refresh")
@limiter.limit("10/minute")
async def refresh_token(request: Request, data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access/refresh token pair."""
    config = get_auth_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="Authentication is not enabled")

    try:
        payload = decode_token(config, data.refresh_token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")  # noqa: B904

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    svc = _get_service(db, config)

    # Validate the refresh token exists in DB (not revoked)
    jti = payload.get("jti")
    if not jti or await svc.validate_refresh_token(jti) is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token has been revoked")

    user = await svc.get_user_by_id(uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    # Revoke old refresh token and issue new pair
    await svc.revoke_refresh_token(jti)
    tokens = await svc.create_tokens(user)
    return {"data": TokenResponse(**tokens, user=UserRead.model_validate(user))}


# Google OAuth


@router.get("/oauth/google")
async def google_login(request: Request):
    """Initiate Google OAuth2 redirect."""
    config = get_auth_config()
    if not config.oauth.google.enabled:
        raise HTTPException(status_code=400, detail="Google OAuth is not enabled")

    oauth = get_oauth()
    if oauth is None:
        raise HTTPException(status_code=500, detail="OAuth not configured")

    redirect_uri = str(request.url_for("google_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/oauth/google/callback", name="google_callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Google OAuth2 callback, create/find user, return JWT tokens."""
    config = get_auth_config()
    if not config.oauth.google.enabled:
        raise HTTPException(status_code=400, detail="Google OAuth is not enabled")

    oauth = get_oauth()
    if oauth is None:
        raise HTTPException(status_code=500, detail="OAuth not configured")

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        raise HTTPException(status_code=400, detail="OAuth authorization failed")  # noqa: B904

    userinfo = token.get("userinfo")
    if not userinfo:
        raise HTTPException(status_code=400, detail="Could not retrieve user info from Google")

    svc = _get_service(db, config)
    user = await svc.get_or_create_google_user(
        email=userinfo["email"],
        google_sub=userinfo["sub"],
        name=userinfo.get("name"),
    )
    if user is None:
        raise HTTPException(status_code=403, detail="Your email domain is not allowed")

    tokens = await svc.create_tokens(user)

    # Generate a short-lived auth code instead of passing tokens in the URL
    code = _secrets.token_urlsafe(32)
    _oauth_code_store[code] = tokens
    frontend_url = f"/?auth_code={code}"
    return RedirectResponse(url=frontend_url)


@router.post("/oauth/exchange")
@limiter.limit("10/minute")
async def exchange_auth_code(request: Request):
    """Exchange a short-lived auth code for JWT tokens (one-time use)."""
    body = await request.json()
    code = body.get("code", "")

    token_data = _oauth_code_store.pop(code, None)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired auth code",
        )

    return {
        "data": {
            "access_token": token_data["access_token"],
            "refresh_token": token_data["refresh_token"],
            "token_type": "bearer",
        }
    }


@router.post("/logout")
async def logout(data: LogoutRequest, db: AsyncSession = Depends(get_db)):
    """Revoke a refresh token (log out)."""
    config = get_auth_config()
    if not config.enabled:
        return {"data": {"message": "Logged out"}}

    try:
        payload = decode_token(config, data.refresh_token)
    except Exception:
        # Token is invalid/expired — already effectively logged out
        return {"data": {"message": "Logged out"}}

    jti = payload.get("jti")
    if jti:
        svc = _get_service(db, config)
        await svc.revoke_refresh_token(jti)

    return {"data": {"message": "Logged out"}}


# Current user endpoints


@router.get("/me")
async def get_me(
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get the current authenticated user's info."""
    config = get_auth_config()
    if not config.enabled:
        return {
            "data": {
                "id": "00000000-0000-0000-0000-000000000000",
                "username": "anonymous",
                "email": None,
                "role": "owner",
                "auth_provider": "local",
                "is_active": True,
                "created_at": "2000-01-01T00:00:00Z",
            }
        }

    if identity.user_id is None:
        raise HTTPException(status_code=400, detail="No user associated with this identity")

    svc = _get_service(db, config)
    user = await svc.get_user_by_id(uuid.UUID(identity.user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return {"data": UserRead.model_validate(user)}


@router.put("/me/password")
async def change_my_password(
    data: PasswordChange,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password."""
    config = get_auth_config()
    if identity.user_id is None:
        raise HTTPException(status_code=400, detail="No user associated with this identity")

    svc = _get_service(db, config)
    user = await svc.get_user_by_id(uuid.UUID(identity.user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.hashed_password and not verify_password(data.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    await svc.change_password(user, data.new_password)
    return {"data": {"message": "Password changed successfully"}}


# Owner: User management


@router.get("/users")
async def list_users(
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """List all users (owner only)."""
    config = get_auth_config()
    svc = _get_service(db, config)
    users = await svc.list_users()
    return {"data": [UserRead.model_validate(u) for u in users]}


@router.post("/users", status_code=201)
async def create_user(
    data: UserCreate,
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (owner only)."""
    config = get_auth_config()
    svc = _get_service(db, config)

    existing = await svc.get_user_by_username(data.username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    if data.email:
        existing_email = await svc.get_user_by_email(data.email)
        if existing_email:
            raise HTTPException(status_code=409, detail="Email already exists")

    user = await svc.create_user(
        username=data.username,
        password=data.password,
        role=data.role,
        email=data.email,
    )
    return {"data": UserRead.model_validate(user)}


@router.put("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Update a user (owner only)."""
    config = get_auth_config()
    svc = _get_service(db, config)
    user = await svc.update_user(user_id, **data.model_dump(exclude_unset=True))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"data": UserRead.model_validate(user)}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user (owner only)."""
    config = get_auth_config()
    svc = _get_service(db, config)
    deleted = await svc.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")


# Owner: Service account management


def _build_sa_read(sa, api_key=None) -> ServiceAccountRead:
    """Build ServiceAccountRead with optional API key info."""
    data = {
        "id": sa.id,
        "name": sa.name,
        "description": sa.description,
        "auth_type": sa.auth_type,
        "google_sa_email": sa.google_sa_email,
        "is_active": sa.is_active,
        "created_at": sa.created_at,
        "api_key": None,
    }
    if api_key:
        data["api_key"] = ServiceAccountKeyInfo(
            key_prefix=api_key.key_prefix,
            last_used_at=api_key.last_used_at,
            expires_at=api_key.expires_at,
            created_at=api_key.created_at,
        )
    return ServiceAccountRead(**data)


@router.get("/service-accounts")
async def list_service_accounts(
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """List all service accounts (owner only)."""
    config = get_auth_config()
    svc = _get_service(db, config)
    accounts = await svc.list_service_accounts()

    result = []
    for sa in accounts:
        api_key = await svc.get_service_account_api_key(sa.id) if sa.auth_type == "api_key" else None
        result.append(_build_sa_read(sa, api_key))

    return {"data": result}


@router.post("/service-accounts", status_code=201)
async def create_service_account(
    data: ServiceAccountCreate,
    identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Create a new service account (owner only).

    For auth_type='api_key', returns the raw API key (only shown once).
    """
    config = get_auth_config()
    svc = _get_service(db, config)
    sa, raw_key = await svc.create_service_account(
        name=data.name,
        auth_type=data.auth_type,
        description=data.description,
        google_sa_email=data.google_sa_email,
        created_by_user_id=uuid.UUID(identity.user_id) if identity.user_id else None,
    )

    api_key = await svc.get_service_account_api_key(sa.id) if sa.auth_type == "api_key" else None
    sa_read = _build_sa_read(sa, api_key)

    return {
        "data": ServiceAccountCreateResponse(
            service_account=sa_read,
            raw_key=raw_key,
        )
    }


@router.post("/service-accounts/{sa_id}/regenerate-key", status_code=200)
async def regenerate_service_account_key(
    sa_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate the API key for a service account (owner only).

    Returns the new raw API key (only shown once).
    """
    config = get_auth_config()
    svc = _get_service(db, config)
    result = await svc.regenerate_api_key(
        sa_id,
        created_by_user_id=uuid.UUID(identity.user_id) if identity.user_id else None,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Service account not found or not an API key type")

    api_key, raw_key = result
    return {"data": {"raw_key": raw_key, "key_prefix": api_key.key_prefix}}


@router.delete("/service-accounts/{sa_id}", status_code=204)
async def delete_service_account(
    sa_id: uuid.UUID,
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Delete a service account (owner only)."""
    config = get_auth_config()
    svc = _get_service(db, config)
    deleted = await svc.delete_service_account(sa_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Service account not found")


# Owner: Model access management


@router.get("/models/{model_id}/access")
async def list_model_access(
    model_id: uuid.UUID,
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """List service accounts with access to a model (owner only)."""
    stmt = select(ModelAccess).where(ModelAccess.model_id == model_id)
    result = await db.execute(stmt)
    entries = list(result.scalars().all())
    return {"data": [ModelAccessRead.model_validate(e) for e in entries]}


@router.post("/models/{model_id}/access", status_code=201)
async def grant_model_access(
    model_id: uuid.UUID,
    data: ModelAccessCreate,
    identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Grant a service account access to a model (owner only)."""
    # Check if access already exists
    stmt = select(ModelAccess).where(
        ModelAccess.model_id == model_id,
        ModelAccess.service_account_id == data.service_account_id,
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Service account already has access to this model")

    access = ModelAccess(
        model_id=model_id,
        service_account_id=data.service_account_id,
        created_by_user_id=uuid.UUID(identity.user_id) if identity.user_id else None,
    )
    db.add(access)
    await db.commit()
    await db.refresh(access)
    return {"data": ModelAccessRead.model_validate(access)}


@router.delete("/models/{model_id}/access/{sa_id}", status_code=204)
async def revoke_model_access(
    model_id: uuid.UUID,
    sa_id: uuid.UUID,
    _identity: CurrentIdentity = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a service account's access to a model (owner only)."""
    stmt = select(ModelAccess).where(
        ModelAccess.model_id == model_id,
        ModelAccess.service_account_id == sa_id,
    )
    result = await db.execute(stmt)
    access = result.scalar_one_or_none()
    if access is None:
        raise HTTPException(status_code=404, detail="Model access entry not found")
    await db.delete(access)
    await db.commit()
