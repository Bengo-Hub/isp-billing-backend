"""Database configuration and session management."""

from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings

# Database metadata
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

# Create async engine
# Ensure we're using asyncpg driver
database_url = settings.database_url
if not database_url.startswith("postgresql+asyncpg://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

# Connection pooling is delegated to PgBouncer (transaction mode) which fronts
# PostgreSQL for every service. Using SQLAlchemy's own QueuePool on top of that
# double-pools: SQLAlchemy holds connections open persistently, and read paths
# that don't explicitly commit/rollback leave them "idle in transaction" at the
# server (observed: 8 leaked BEGIN connections held up to ~19min). NullPool makes
# each session acquire and fully release a real connection, so nothing lingers
# idle-in-transaction — PgBouncer keeps the warm server-side pool. pool_size /
# max_overflow / pool_pre_ping do not apply to NullPool and are intentionally
# dropped (config values retained for reference only).
engine = create_async_engine(
    database_url,
    echo=settings.debug,
    poolclass=NullPool,
)

# Create async session factory
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Create declarative base
Base = declarative_base(metadata=metadata)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Verify database connection. Tables are managed by Alembic migrations."""
    from sqlalchemy import text
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
