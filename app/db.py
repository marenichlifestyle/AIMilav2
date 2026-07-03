from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base


engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS ai_state text NOT NULL DEFAULT 'active'"))
        await conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS ai_paused_at timestamptz NULL"))
        await conn.execute(text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS ai_paused_reason text NULL"))
        await conn.execute(text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS ignored_reason text NULL"))
