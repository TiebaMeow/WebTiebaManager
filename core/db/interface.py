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

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from core.control import Controller

from .config import DatabaseConfig
from .models import Base, ContentModel, ForumModel, LifeModel, UserModel


class Database:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]

    @classmethod
    async def startup(cls, _: None = None) -> None:
        config = Controller.config
        database_config = DatabaseConfig.model_validate(config.database)
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
    async def save_items[T: (ContentModel, ForumModel, LifeModel, UserModel)](cls, items: Iterable[T]) -> None:
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

    @classmethod
    async def get_thread_by_tid(cls, tid: int) -> ContentModel | None:
        async with cls.get_session() as session:
            result = await session.execute(
                select(ContentModel).where(ContentModel.tid == tid, ContentModel.type == "thread")
            )
            return result.scalars().first()


Controller.Start.on(Database.startup)
Controller.Stop.on(Database.teardown)
