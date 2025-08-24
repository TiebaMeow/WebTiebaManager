"""
使用方法：

from core.typedef import Content
from core.db import Database, ContentModel

contents: list[Content]
content_models = [ContentModel.from_content(c) for c in contents]
await Database.save_items(content_models)

pids = [1, 2, 3]
result = await Database.get_contents_by_pids(pids)
"""

from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, TypeVar
from urllib.parse import quote_plus

from pydantic import BaseModel, computed_field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from core.control import Controller

from .models import Base, ContentModel, ForumModel, LifeModel, UserModel

ModelType = TypeVar("ModelType", ContentModel, ForumModel, LifeModel, UserModel)


class DatabaseConfig(BaseModel, extra="ignore"):
    type: Literal["sqlite", "postgresql", "mysql"]
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
            url_path = Path(self.path).resolve().as_posix()
            return f"sqlite+aiosqlite:///{url_path}"
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
        cls.engine = create_async_engine(
            database_config.database_url,
            pool_pre_ping=(database_config.type != "sqlite"),
        )
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
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    @classmethod
    async def save_items(cls, items: Iterable[ModelType]) -> None:
        item_list = list(items)
        if not item_list:
            return
        async with cls.get_session() as session:
            session.add_all(item_list)
            await session.commit()

    @classmethod
    async def get_contents_by_pids(cls, pids: Iterable[int]) -> list[ContentModel]:
        pid_list = list(pids)
        if not pid_list:
            return []
        async with cls.get_session() as session:
            result = await session.execute(select(ContentModel).where(ContentModel.pid.in_(pid_list)))
            return list(result.scalars().all())


Controller.Start.on(Database.startup)
Controller.Stop.on(Database.teardown)
