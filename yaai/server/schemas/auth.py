"""Pydantic schemas for authentication API requests/responses."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105
    user: "UserRead"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class AuthConfigResponse(BaseModel):
    enabled: bool
    local_enabled: bool
    google_oauth_enabled: bool
    allow_registration: bool


class UserRead(BaseModel):
    id: uuid.UUID
    username: str
    email: str | None
    role: str
    auth_provider: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    email: str | None = None
    password: str = Field(..., min_length=8)
    role: str = "viewer"


class UserUpdate(BaseModel):
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class ServiceAccountKeyInfo(BaseModel):
    """API key info returned with service account (prefix only, not full key)."""

    key_prefix: str
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class ServiceAccountRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    auth_type: str
    google_sa_email: str | None
    is_active: bool
    created_at: datetime
    api_key: ServiceAccountKeyInfo | None = None  # Only for auth_type=api_key

    model_config = {"from_attributes": True}


class ServiceAccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    auth_type: str = "api_key"  # "api_key" or "google"
    google_sa_email: str | None = None


class ServiceAccountCreateResponse(BaseModel):
    """Response when creating a service account. Includes raw_key for api_key type."""

    service_account: ServiceAccountRead
    raw_key: str | None = None  # Only returned once for auth_type=api_key


class APIKeyRead(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    is_active: bool
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    service_account_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    service_account_id: uuid.UUID | None = None
    expires_at: datetime | None = None


class APIKeyCreateResponse(BaseModel):
    api_key: APIKeyRead
    raw_key: str


class ModelAccessRead(BaseModel):
    id: uuid.UUID
    model_id: uuid.UUID
    service_account_id: uuid.UUID
    created_at: datetime
    created_by_user_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class ModelAccessCreate(BaseModel):
    service_account_id: uuid.UUID
