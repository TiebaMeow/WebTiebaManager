"""
使用方法：

from src.typedef import Content
from src.db import Database, ContentModel

contents: list[Content]
content_models = [ContentModel.from_content(c) for c in contents]
await Database.save_items(content_models)

pids = [1, 2, 3]
result = await Database.get_contents_by_pids(pids)
"""

from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.control import Controller
from src.util.logging import system_logger

from .config import DatabaseConfig
from .models import Base, ContentModel, ForumModel, LifeModel, UserModel


class Database:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]

    @classmethod
    async def startup(cls, _: None = None) -> None:
        config = Controller.config
        system_logger.info("初始化数据库连接...")
        system_logger.info(f"数据库类型: {config.database.type}")
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
        system_logger.info("关闭数据库连接...")
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
    async def save_items[T: (ContentModel, ForumModel, LifeModel, UserModel)](
        cls,
        items: Iterable[T],
        *,
        on_conflict: Literal["ignore", "upsert"] = "ignore",
        exclude_columns: Iterable[str] | None = None,
        chunk_size: int | None = 1000,
    ) -> None:
        """
        批量保存模型，支持主键冲突处理：忽略或 UPSERT。

        兼容方言:
        - SQLite: ON CONFLICT DO NOTHING / DO UPDATE
        - PostgreSQL: ON CONFLICT DO NOTHING / DO UPDATE
        - MySQL: INSERT IGNORE / ON DUPLICATE KEY UPDATE

        Attributes:
            items(Iterable[T]): 同一模型类型的实例序列。
            on_conflict(Literal["ignore", "upsert"]): 冲突处理策略，"ignore" 忽略，"upsert" 根据主键更新非主键列。
            exclude_columns(Iterable[str]): 当 on_conflict="upsert" 时指定不需要更新的列名（如"create_time"）；
                                            默认更新所有非主键列。
            chunk_size(int | None): 分批处理的批次大小，None 或 <=0 则不分批。

        Raises:
            TypeError: items 中包含不同模型类型的实例。
        """
        item_list = list(items)
        if not item_list:
            return

        model: type[T] = type(item_list[0])
        if not all(isinstance(i, model) for i in item_list):
            raise TypeError

        table = model.__table__
        columns = list(table.columns)
        pk_cols = [c for c in columns if c.primary_key]
        non_pk_cols = [c for c in columns if not c.primary_key]

        update_cols: set[str] = set()
        if on_conflict == "upsert":
            if exclude_columns is None:
                update_cols = {c.name for c in non_pk_cols}
            else:
                exclude_set = set(exclude_columns)
                update_cols = {c.name for c in non_pk_cols if c.name not in exclude_set}
                if not update_cols:
                    on_conflict = "ignore"

        rows: list[dict] = []
        for inst in item_list:
            row: dict = {}
            for c in columns:
                v = getattr(inst, c.name)
                if v is not None:
                    row[c.name] = v
            rows.append(row)

        dialect = cls.engine.dialect.name
        pk_names = [c.name for c in pk_cols]
        pk_index_elems = [table.c[name] for name in pk_names]

        # 分批处理
        batches: list[list[dict]]
        if chunk_size and chunk_size > 0 and len(rows) > chunk_size:
            batches = [rows[i : i + chunk_size] for i in range(0, len(rows), chunk_size)]
        else:
            batches = [rows]

        stmt = None
        if dialect == "mysql":
            stmt = mysql_insert(model)
            if on_conflict == "ignore":
                stmt = stmt.prefix_with("IGNORE")  # INSERT IGNORE
            else:  # upsert
                stmt = stmt.on_duplicate_key_update({name: stmt.inserted[name] for name in update_cols})

        elif dialect == "postgresql":
            stmt = pg_insert(model)
            if on_conflict == "ignore":
                stmt = stmt.on_conflict_do_nothing(index_elements=pk_index_elems)
            else:  # upsert
                stmt = stmt.on_conflict_do_update(
                    index_elements=pk_index_elems,
                    set_={name: stmt.excluded[name] for name in update_cols},
                )
        elif dialect == "sqlite":
            stmt = sqlite_insert(model)
            if on_conflict == "ignore":
                stmt = stmt.on_conflict_do_nothing(index_elements=pk_index_elems)
            else:  # upsert
                stmt = stmt.on_conflict_do_update(
                    index_elements=pk_index_elems,
                    set_={name: stmt.excluded[name] for name in update_cols},
                )

        async with cls.get_session() as session:
            if stmt is not None:
                for batch in batches:
                    await session.execute(stmt.values(batch))
                await session.commit()
                return

            # 回退到普通 add_all（不支持冲突处理）
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

    @classmethod
    async def iter_all_contents(cls) -> AsyncGenerator[ContentModel, None]:
        async with cls.get_session() as session:
            result = await session.stream(select(ContentModel))
            async for row in result.scalars():
                yield row

    @classmethod
    async def delete_contents_by_pids(cls, pids: Iterable[int]) -> None:
        pid_list = list(pids)
        if not pid_list:
            return
        async with cls.get_session() as session:
            await session.execute(delete(ContentModel).where(ContentModel.pid.in_(pid_list)))
            await session.commit()


Controller.Start.on(Database.startup)
Controller.Stop.on(Database.teardown)
