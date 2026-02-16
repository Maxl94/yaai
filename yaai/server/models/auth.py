"""SQLAlchemy models for authentication: User, ServiceAccount, APIKey, ModelAccess."""

import enum
import uuid as uuid_mod
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yaai.server.database import Base, UUIDMixin


class UserRole(enum.StrEnum):
    OWNER = "owner"
    VIEWER = "viewer"


class AuthProvider(enum.StrEnum):
    LOCAL = "local"
    GOOGLE = "google"


class User(UUIDMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.VIEWER)
    auth_provider: Mapped[AuthProvider] = mapped_column(Enum(AuthProvider), nullable=False, default=AuthProvider.LOCAL)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="created_by_user", cascade="all, delete-orphan")


class ServiceAccount(UUIDMixin, Base):
    __tablename__ = "service_accounts"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "api_key" or "google_sa"
    google_sa_email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="service_account", cascade="all, delete-orphan")
    model_access: Mapped[list["ModelAccess"]] = relationship(
        back_populates="service_account", cascade="all, delete-orphan"
    )


class APIKey(UUIDMixin, Base):
    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    service_account_id: Mapped[uuid_mod.UUID | None] = mapped_column(
        ForeignKey("service_accounts.id", ondelete="CASCADE"), nullable=True
    )
    created_by_user_id: Mapped[uuid_mod.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    service_account: Mapped[ServiceAccount | None] = relationship(back_populates="api_keys")
    created_by_user: Mapped[User | None] = relationship(back_populates="api_keys")


class ModelAccess(UUIDMixin, Base):
    __tablename__ = "model_access"
    __table_args__ = (UniqueConstraint("model_id", "service_account_id", name="uq_model_sa_access"),)

    model_id: Mapped[uuid_mod.UUID] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    service_account_id: Mapped[uuid_mod.UUID] = mapped_column(
        ForeignKey("service_accounts.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by_user_id: Mapped[uuid_mod.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    service_account: Mapped[ServiceAccount] = relationship(back_populates="model_access")


class RefreshToken(UUIDMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid_mod.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    jti: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
