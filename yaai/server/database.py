"""Async SQLAlchemy engine, session factory, and base model."""

import uuid as uuid_mod
from collections.abc import AsyncGenerator

from sqlalchemy import Uuid
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from yaai.server.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class UUIDMixin:
    """Mixin providing a UUID primary key for all models."""

    id: Mapped[uuid_mod.UUID] = mapped_column(Uuid, primary_key=True, default=uuid_mod.uuid4)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session() as session:
        yield session
