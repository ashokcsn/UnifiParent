import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///parental_control.db")

engine = create_async_engine(
    DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
)
async_session = async_sessionmaker(engine, expire_on_commit=False)

Base = declarative_base()

async def get_db():
    async with async_session() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safely add the new column to existing databases
        from sqlalchemy import text
        try:
            await conn.execute(text("ALTER TABLE profiles ADD COLUMN audit_only BOOLEAN DEFAULT 0"))
        except Exception:
            pass # Column already exists
    
    # Seed default categories
    from sqlalchemy.future import select
    from .schema import Category
    
    async with async_session() as session:
        result = await session.execute(select(Category).limit(1))
        if not result.scalars().first():
            defaults = [
                Category(name="YouTube", domains="youtube.com, googlevideo.com, ytimg.com"),
                Category(name="Facebook", domains="facebook.com, fbcdn.net, fbsbx.com"),
                Category(name="Instagram", domains="instagram.com, cdninstagram.com"),
                Category(name="Chess.com", domains="chess.com, chesscomfiles.com")
            ]
            session.add_all(defaults)
            await session.commit()
