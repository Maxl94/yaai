"""Pagination utilities for database queries."""

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def paginate_query(
    db: AsyncSession,
    query: Select,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Any], int]:
    """Execute a query with pagination and return results with total count.

    Args:
        db: Async database session.
        query: Base SQLAlchemy select query (without offset/limit).
        page: 1-based page number.
        page_size: Maximum number of results per page.

    Returns:
        A tuple of (list of results, total count).
    """
    # Count total matching rows
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    # Apply pagination
    paginated = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(paginated)

    return list(result.scalars().all()), total
