"""Pydantic schemas for projects shared between the SDK and the server."""

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel


class ProjectRole(enum.StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class ProjectRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_default: bool
    model_count: int
    my_role: ProjectRole | None = None
    created_at: datetime
    updated_at: datetime
