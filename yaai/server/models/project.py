"""SQLAlchemy models for projects and project memberships (access control scope for models)."""

import uuid as uuid_mod
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from yaai.schemas.project import ProjectRole
from yaai.server.database import Base, UUIDMixin

DEFAULT_PROJECT_NAME = "default"


# Roles that may modify a project's models
WRITE_ROLES = (ProjectRole.OWNER, ProjectRole.EDITOR)


class Project(UUIDMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectMembership(UUIDMixin, Base):
    """Grants a user or a service account a role within a project (exactly one principal per row)."""

    __tablename__ = "project_memberships"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NULL) <> (service_account_id IS NULL)", name="ck_project_memberships_one_principal"
        ),
        UniqueConstraint("user_id", "project_id", name="uq_project_memberships_user"),
        UniqueConstraint("service_account_id", "project_id", name="uq_project_memberships_sa"),
        Index("ix_project_memberships_project", "project_id"),
    )

    project_id: Mapped[uuid_mod.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid_mod.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    service_account_id: Mapped[uuid_mod.UUID | None] = mapped_column(
        ForeignKey("service_accounts.id", ondelete="CASCADE"), nullable=True
    )
    role: Mapped[ProjectRole] = mapped_column(Enum(ProjectRole), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
