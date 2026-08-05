"""This module provides database connection utilities."""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """This class provides the declarative base for application models that the database stores."""


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """This function creates the application engine when the application first uses the database."""
    return create_async_engine(str(get_settings().database_url), pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """This function returns the asynchronous session factory for the process."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """This function provides a database session for dependency injection."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
