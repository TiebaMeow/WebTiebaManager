"""
使用方法：

from core.db import Database, Content, Life

contents = [Content(**{"fid": i, "fname": f"test_{i}"}) for i in range(1, 4)]
await Database.save_items(contents)

fids = [1, 2, 3]
result = await Database.get_contents(fids)
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from urllib.parse import quote_plus

from pydantic import BaseModel, computed_field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from core.control import Controller

from .models import Base, Content, Life

ModelType = Content | Life


class DatabaseConfig(BaseModel, extra="ignore"):
    type: str
    path: str | None = None
    username: str | None = None
    password: str | None = None
    host: str | None = None
    port: int | None = None
    db: str | None = None

    @computed_field
    @property
    def database_url(self) -> str:
        if self.type == "sqlite":
            if not self.path:
                raise ValueError("SQLite database path is required")
            return f"sqlite+aiosqlite:///{self.path}"
        if not all([self.username, self.password, self.host, self.port, self.db]):
            raise ValueError("Database configuration is incomplete")
        if self.type == "postgresql":
            return (
                f"postgresql+asyncpg://"
                f"{quote_plus(self.username)}:{quote_plus(self.password)}"  # type: ignore
                f"@{self.host}:{self.port}/{self.db}"
            )
        elif self.type == "mysql":
            return (
                f"mysql+asyncmy://"
                f"{quote_plus(self.username)}:{quote_plus(self.password)}"  # type: ignore
                f"@{self.host}:{self.port}/{self.db}"
            )
        else:
            raise ValueError("Unsupported database type")


class Database:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]

    @classmethod
    async def startup(cls, _: None = None) -> None:
        config = Controller.config
        database_config = DatabaseConfig.model_validate(config)
        cls.engine = create_async_engine(database_config.database_url)
        cls.sessionmaker = async_sessionmaker(cls.engine, class_=AsyncSession, expire_on_commit=False)
        async with cls.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @classmethod
    async def teardown(cls, _: None = None) -> None:
        await cls.engine.dispose()

    @classmethod
    @asynccontextmanager
    async def get_session(cls) -> AsyncGenerator[AsyncSession, None]:
        async with cls.sessionmaker() as session:
            try:
                yield session
            except SQLAlchemyError:
                await session.rollback()
                raise
            finally:
                await session.close()

    @classmethod
    async def save_items(cls, items: list[ModelType]) -> None:
        async with cls.get_session() as session:
            session.add_all(item for item in items)
            await session.commit()

    @classmethod
    async def get_contents(cls, fids: list[int]) -> list[Content]:
        async with cls.get_session() as session:
            result = await session.execute(select(Content).where(Content.fid.in_(fids)))
            return list(result.scalars().all())


Controller.Start.on(Database.startup)
Controller.Stop.on(Database.teardown)
