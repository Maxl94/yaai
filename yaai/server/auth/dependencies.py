"""FastAPI dependency injection for authentication and authorization."""

from __future__ import annotations

import uuid

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.auth.config import AuthConfig
from yaai.server.auth.service_auth import validate_api_key, validate_google_sa_token
from yaai.server.database import get_db
from yaai.server.models.auth import ModelAccess, UserRole

# Global auth config reference, set at startup
_auth_config: AuthConfig | None = None


def set_auth_config(config: AuthConfig) -> None:
    global _auth_config
    _auth_config = config


def get_auth_config() -> AuthConfig:
    if _auth_config is None:
        return AuthConfig()
    return _auth_config


# Optional bearer: does NOT auto-raise 403 when missing
optional_bearer = HTTPBearer(auto_error=False)


class CurrentIdentity:
    """Represents the authenticated identity (user, API key, or service account)."""

    def __init__(
        self,
        user_id: str | None,
        role: UserRole,
        identity_type: str = "user",
        username: str | None = None,
        service_account_id: str | None = None,
    ):
        self.user_id = user_id
        self.role = role
        self.identity_type = identity_type
        self.username = username
        self.service_account_id = service_account_id

    @property
    def is_owner(self) -> bool:
        return self.role == UserRole.OWNER

    @property
    def is_service_account(self) -> bool:
        return self.identity_type in ("api_key", "google_sa")


async def _try_jwt(config: AuthConfig, token: str) -> CurrentIdentity | None:
    """Try to decode a JWT access token."""
    try:
        from yaai.server.auth.jwt import decode_token

        payload = decode_token(config, token)
        if payload.get("type") != "access":
            return None
        return CurrentIdentity(
            user_id=payload["sub"],
            role=UserRole(payload["role"]),
            identity_type="user",
        )
    except pyjwt.PyJWTError:
        return None


async def _try_api_key(config: AuthConfig, key_value: str, db: AsyncSession) -> CurrentIdentity | None:
    """Try to validate an API key."""
    result = await validate_api_key(config, key_value, db)
    if result is None:
        return None

    sa_id = result.get("service_account_id")
    # API keys are now always linked to service accounts
    # Service accounts have per-model access restrictions (role=VIEWER)

    return CurrentIdentity(
        user_id=sa_id,
        role=UserRole.VIEWER,
        identity_type="api_key",
        service_account_id=sa_id,
    )


async def _try_google_sa(config: AuthConfig, token: str, db: AsyncSession) -> CurrentIdentity | None:
    """Try to validate a Google Service Account OAuth2 token."""
    result = await validate_google_sa_token(config, token, db)
    if result is None:
        return None
    return CurrentIdentity(
        user_id=None,
        role=UserRole.VIEWER,  # SAs have no global role; access is per-model
        identity_type="google_sa",
        username=result.get("email"),
        service_account_id=result.get("service_account_id"),
    )


async def get_current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> CurrentIdentity | None:
    """Core authentication dependency.

    When auth is disabled, returns None (all access granted).
    When auth is enabled, validates Bearer JWT, Bearer API key, X-API-Key header,
    or Bearer Google SA token.
    """
    config = get_auth_config()
    if not config.enabled:
        return None

    token = credentials.credentials if credentials else None

    if token:
        # 1. Try JWT Bearer token
        identity = await _try_jwt(config, token)
        if identity:
            return identity

        # 2. Try API key as Bearer token
        identity = await _try_api_key(config, token, db)
        if identity:
            return identity

        # 3. Try Google SA token
        identity = await _try_google_sa(config, token, db)
        if identity:
            return identity

    # 4. Try X-API-Key header
    if x_api_key:
        identity = await _try_api_key(config, x_api_key, db)
        if identity:
            return identity

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def require_auth(
    identity: CurrentIdentity | None = Depends(get_current_identity),
) -> CurrentIdentity:
    """Dependency that requires authentication (any role)."""
    config = get_auth_config()
    if not config.enabled:
        return CurrentIdentity(user_id=None, role=UserRole.OWNER, identity_type="anonymous", username="anonymous")
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return identity


def require_owner(
    identity: CurrentIdentity = Depends(require_auth),
) -> CurrentIdentity:
    """Dependency that requires owner role."""
    config = get_auth_config()
    if not config.enabled:
        return identity
    if not identity.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required")
    return identity


async def require_model_write(
    model_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> CurrentIdentity:
    """Require write access for a specific model.

    Owner → always allowed.
    Service account (API key or Google SA) → only if whitelisted for this model.
    Viewer → denied.
    """
    config = get_auth_config()
    if not config.enabled:
        return identity
    if identity.is_owner:
        return identity
    if identity.role == UserRole.VIEWER and not identity.is_service_account:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot modify resources")
    if identity.is_service_account:
        sa_id = identity.service_account_id
        if sa_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Service account identity missing")
        stmt = select(ModelAccess).where(
            ModelAccess.model_id == model_id,
            ModelAccess.service_account_id == uuid.UUID(sa_id),
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Service account not whitelisted for this model",
            )
        return identity
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


async def check_model_write_access(
    model_id: uuid.UUID,
    identity: CurrentIdentity,
    db: AsyncSession,
) -> None:
    """Check write access for a specific model. Raises HTTPException if denied.

    Use this in endpoint functions where model_id is not a path parameter
    (e.g. resolved from request body).
    """
    config = get_auth_config()
    if not config.enabled:
        return
    if identity.is_owner:
        return
    if identity.role == UserRole.VIEWER and not identity.is_service_account:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot modify resources")
    if identity.is_service_account:
        sa_id = identity.service_account_id
        if sa_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Service account identity missing")
        stmt = select(ModelAccess).where(
            ModelAccess.model_id == model_id,
            ModelAccess.service_account_id == uuid.UUID(sa_id),
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Service account not whitelisted for this model",
            )
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


async def resolve_model_id_from_version(model_version_id: uuid.UUID, db: AsyncSession) -> uuid.UUID:
    """Look up the model_id for a given model_version_id."""
    from yaai.server.models.model import ModelVersion

    stmt = select(ModelVersion.model_id).where(ModelVersion.id == model_version_id)
    result = await db.execute(stmt)
    model_id = result.scalar_one_or_none()
    if model_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model version not found")
    return model_id


async def resolve_model_id_from_job(job_id: uuid.UUID, db: AsyncSession) -> uuid.UUID:
    """Look up the model_id for a given job_id (job → version → model)."""
    from yaai.server.models.job import JobConfig
    from yaai.server.models.model import ModelVersion

    stmt = (
        select(ModelVersion.model_id)
        .join(JobConfig, JobConfig.model_version_id == ModelVersion.id)
        .where(JobConfig.id == job_id)
    )
    result = await db.execute(stmt)
    model_id = result.scalar_one_or_none()
    if model_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return model_id


async def check_model_read_access(
    model_id: uuid.UUID,
    identity: CurrentIdentity,
    db: AsyncSession,
) -> None:
    """Check read access for a specific model. Raises HTTPException if denied.

    Non-SA identities (users): always allowed.
    Service accounts: only allowed if whitelisted via ModelAccess.
    """
    config = get_auth_config()
    if not config.enabled:
        return
    if not identity.is_service_account:
        return
    sa_id = identity.service_account_id
    if sa_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Service account identity missing")
    stmt = select(ModelAccess).where(
        ModelAccess.model_id == model_id,
        ModelAccess.service_account_id == uuid.UUID(sa_id),
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Service account not whitelisted for this model",
        )


async def get_accessible_model_ids(
    identity: CurrentIdentity,
    db: AsyncSession,
) -> list[uuid.UUID] | None:
    """Return the list of model IDs a service account can access, or None if no filtering needed.

    Non-SA identities: returns None (no filtering).
    Service accounts: returns list of model_ids from ModelAccess.
    """
    config = get_auth_config()
    if not config.enabled:
        return None
    if not identity.is_service_account:
        return None
    sa_id = identity.service_account_id
    if sa_id is None:
        return []
    stmt = select(ModelAccess.model_id).where(
        ModelAccess.service_account_id == uuid.UUID(sa_id),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
