"""Pydantic schemas for project and project membership API requests/responses."""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from yaai.schemas.project import ProjectRole


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class ProjectMemberCreate(BaseModel):
    """Exactly one of user_id, username or service_account_id identifies the principal to add."""

    user_id: uuid.UUID | None = None
    username: str | None = Field(None, min_length=1)
    service_account_id: uuid.UUID | None = None
    role: ProjectRole

    @model_validator(mode="after")
    def _exactly_one_principal(self) -> Self:
        if sum(value is not None for value in (self.user_id, self.username, self.service_account_id)) != 1:
            raise ValueError("Exactly one of user_id, username or service_account_id is required")
        return self


class ProjectMemberUpdate(BaseModel):
    role: ProjectRole


class ProjectMemberRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    principal_type: str  # "user" or "service_account"
    user_id: uuid.UUID | None
    service_account_id: uuid.UUID | None
    name: str  # username or service account name
    email: str | None
    role: ProjectRole
    created_at: datetime
