"""Async SQLAlchemy engine, session factory, and base model."""

import uuid as uuid_mod
from collections.abc import AsyncGenerator

from sqlalchemy import Uuid
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from yaai.server.config import settings

engine = None
async_session = None


def init_engine(async_creator=None):
    """Initialize the async engine and session factory.

    Args:
        async_creator: Optional async callable for Cloud SQL Connector.
                       When provided, creates engine with async_creator param.
    """
    global engine, async_session
    if async_creator is not None:
        engine = create_async_engine(
            "postgresql+asyncpg://",
            async_creator=async_creator,
            echo=False,
        )
    else:
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


# Initialize eagerly when not using Cloud SQL (preserves existing behavior).
# When Cloud SQL is configured, init_engine() is called from the lifespan handler.
if not settings.cloud_sql_instance:
    init_engine()
