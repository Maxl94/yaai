"""FastAPI dependency injection for authentication and authorization."""

from __future__ import annotations

import uuid

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import ColumnElement, Select, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.auth.config import AuthConfig
from yaai.server.auth.jwt import decode_token
from yaai.server.auth.service_auth import validate_api_key, validate_google_sa_token, validate_google_user_token
from yaai.server.database import get_db
from yaai.server.models.auth import ModelAccess, User, UserRole
from yaai.server.models.job import JobConfig
from yaai.server.models.model import Model, ModelVersion
from yaai.server.models.project import WRITE_ROLES, Project, ProjectMembership, ProjectRole

# Global auth config reference, set at startup
_auth_config: AuthConfig | None = None


def set_auth_config(config: AuthConfig) -> None:
    global _auth_config  # noqa: PLW0603
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


async def _try_jwt(config: AuthConfig, token: str, db: AsyncSession) -> CurrentIdentity | None:
    """Try to decode a JWT access token and resolve the user from the database.

    Returns None if the token is not a valid access JWT (so other credential types can be tried).
    The role is taken from the database so role changes apply immediately.

    Raises:
        HTTPException: 401 if the token is a valid access JWT but its user is missing, inactive or malformed.
    """
    try:
        payload = decode_token(config, token)
    except pyjwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None

    try:
        user = await db.get(User, uuid.UUID(str(payload.get("sub"))))
    except ValueError:
        user = None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    return CurrentIdentity(
        user_id=str(user.id),
        role=user.role,
        identity_type="user",
        username=user.username,
    )


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


async def _try_google_user(config: AuthConfig, token: str, db: AsyncSession) -> CurrentIdentity | None:
    """Try to validate a Google user ID token (from gcloud CLI or SDK)."""
    result = await validate_google_user_token(config, token, db)
    if result is None:
        return None
    return CurrentIdentity(
        user_id=result["user_id"],
        role=UserRole(result["role"]),
        identity_type="user",
        username=result.get("email"),
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
        identity = await _try_jwt(config, token, db)
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

        # 4. Try Google user ID token (gcloud auth print-identity-token)
        identity = await _try_google_user(config, token, db)
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


def require_owner_or_service_account(
    identity: CurrentIdentity = Depends(require_auth),
) -> CurrentIdentity:
    """Dependency that allows owners and service accounts, but denies viewers."""
    config = get_auth_config()
    if not config.enabled:
        return identity
    if not identity.is_owner and not identity.is_service_account:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot modify resources")
    return identity


def has_global_access(identity: CurrentIdentity) -> bool:
    """True if authentication is disabled or the identity is a global owner (super-admin)."""
    return not get_auth_config().enabled or identity.is_owner


def _membership_filter(identity: CurrentIdentity) -> ColumnElement[bool] | None:
    """Membership rows of the identity (user or service account), None if it has no usable ID."""
    principal_id = identity.service_account_id if identity.is_service_account else identity.user_id
    if principal_id is None:
        return None
    column = ProjectMembership.service_account_id if identity.is_service_account else ProjectMembership.user_id
    return column == uuid.UUID(principal_id)


async def get_project_roles(identity: CurrentIdentity, db: AsyncSession) -> dict[uuid.UUID, ProjectRole]:
    """Return the project roles granted to the identity through memberships (empty for global access).

    Global owners and disabled authentication are not expressed as memberships; callers must check
    ``has_global_access`` first if they need the effective role.
    """
    membership_filter = _membership_filter(identity)
    if membership_filter is None:
        return {}
    result = await db.execute(select(ProjectMembership.project_id, ProjectMembership.role).where(membership_filter))
    return dict(result.tuples().all())


async def get_project_role(identity: CurrentIdentity, project_id: uuid.UUID, db: AsyncSession) -> ProjectRole | None:
    """Effective role of the identity in a project, or None if it has no access.

    Single source of truth for project permissions. Disabled authentication and global owners
    are treated as project owners; everybody else needs a membership (users and service accounts alike).
    """
    if has_global_access(identity):
        return ProjectRole.OWNER
    membership_filter = _membership_filter(identity)
    if membership_filter is None:
        return None
    result = await db.execute(
        select(ProjectMembership.role).where(ProjectMembership.project_id == project_id, membership_filter)
    )
    return result.scalar_one_or_none()


async def get_project_role_for_model(
    identity: CurrentIdentity, model_id: uuid.UUID, db: AsyncSession
) -> ProjectRole | None:
    """Effective role of the identity in the project that contains the model.

    Raises:
        HTTPException: 404 if the model does not exist.
    """
    if has_global_access(identity):
        return ProjectRole.OWNER
    project_id = (await db.execute(select(Model.project_id).where(Model.id == model_id))).scalar_one_or_none()
    if project_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    return await get_project_role(identity, project_id, db)


def _reject_service_account_without_id(identity: CurrentIdentity) -> None:
    if identity.is_service_account and identity.service_account_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Service account identity missing")


async def _service_account_has_model_access(identity: CurrentIdentity, model_id: uuid.UUID, db: AsyncSession) -> bool:
    """Whether the service account is whitelisted for the model through a ModelAccess entry."""
    sa_id = identity.service_account_id
    if not identity.is_service_account or sa_id is None:
        return False
    stmt = select(ModelAccess.id).where(
        ModelAccess.model_id == model_id, ModelAccess.service_account_id == uuid.UUID(sa_id)
    )
    return (await db.execute(stmt)).first() is not None


async def check_model_write_access(
    model_id: uuid.UUID,
    identity: CurrentIdentity,
    db: AsyncSession,
) -> None:
    """Check write access for a specific model. Raises HTTPException if denied.

    Global owner -> always allowed.
    Users -> editor or owner role in the model's project.
    Service accounts -> whitelisted via ModelAccess, or editor/owner role in the model's project.

    Use this in endpoint functions where model_id is not a path parameter
    (e.g. resolved from request body).
    """
    if has_global_access(identity):
        return
    _reject_service_account_without_id(identity)
    role = await get_project_role_for_model(identity, model_id, db)
    if role in WRITE_ROLES or await _service_account_has_model_access(identity, model_id, db):
        return
    if identity.is_service_account:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Service account not whitelisted for this model"
        )
    if role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the project of this model")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot modify resources")


async def require_model_write(
    model_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> CurrentIdentity:
    """Require write access for the model in the ``model_id`` path parameter (see check_model_write_access)."""
    await check_model_write_access(model_id, identity, db)
    return identity


async def require_project_admin(
    project_id: uuid.UUID,
    identity: CurrentIdentity = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> CurrentIdentity:
    """Require permission to manage a project: global owner or project owner (users only).

    Raises:
        HTTPException: 404 if the project does not exist, 403 if the identity may not manage it.
    """
    if has_global_access(identity):
        return identity
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    role = await get_project_role(identity, project_id, db)
    if identity.is_service_account or role != ProjectRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project owner access required")
    return identity


async def resolve_model_id_from_version(model_version_id: uuid.UUID, db: AsyncSession) -> uuid.UUID:
    """Look up the model_id for a given model_version_id."""
    stmt = select(ModelVersion.model_id).where(ModelVersion.id == model_version_id)
    result = await db.execute(stmt)
    model_id = result.scalar_one_or_none()
    if model_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model version not found")
    return model_id


async def resolve_model_id_from_job(job_id: uuid.UUID, db: AsyncSession) -> uuid.UUID:
    """Look up the model_id for a given job_id (job → version → model)."""
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

    Global owner -> always allowed.
    Users -> any role in the model's project.
    Service accounts -> whitelisted via ModelAccess, or any role in the model's project.
    """
    if has_global_access(identity):
        return
    _reject_service_account_without_id(identity)
    role = await get_project_role_for_model(identity, model_id, db)
    if role is not None or await _service_account_has_model_access(identity, model_id, db):
        return
    if identity.is_service_account:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Service account not whitelisted for this model"
        )
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No access to the project of this model")


async def check_version_read_access(
    model_id: uuid.UUID,
    version_id: uuid.UUID,
    identity: CurrentIdentity,
    db: AsyncSession,
) -> None:
    """Check read access for a model and ensure the version belongs to it.

    Use this for routes that take both IDs from the path but query by version_id,
    so access granted on one model cannot be used to read another model's version.

    Raises:
        HTTPException: 403 if access is denied, 404 if the version does not belong to the model.
    """
    await check_model_read_access(model_id, identity, db)
    if await resolve_model_id_from_version(version_id, db) != model_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model version not found")


async def get_accessible_model_ids(
    identity: CurrentIdentity,
    db: AsyncSession,
) -> Select | None:
    """Return a subquery of the model IDs the identity may read, or None if no filtering is needed.

    Pass the result to ``.in_()``; it is evaluated inside the database, not materialized in Python.
    ``db`` is unused and only kept for call-site symmetry with the other access helpers.

    Global owners (and disabled authentication): None (no filtering).
    Users: models of the projects they are a member of.
    Service accounts: models they are whitelisted for (ModelAccess) plus models of their projects.
    """
    if has_global_access(identity):
        return None
    membership_filter = _membership_filter(identity)
    if membership_filter is None:
        return select(Model.id).where(false())
    conditions = [Model.project_id.in_(select(ProjectMembership.project_id).where(membership_filter))]
    if identity.is_service_account:
        conditions.append(
            Model.id.in_(
                select(ModelAccess.model_id).where(
                    ModelAccess.service_account_id == uuid.UUID(identity.service_account_id)
                )
            )
        )
    return select(Model.id).where(or_(*conditions))
