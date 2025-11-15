"""
使用方法：

from src.schemas.tieba import Content
from src.db import Database, ContentModel

contents: list[Content]
content_models = [ContentModel.from_content(c) for c in contents]
await Database.save_items(content_models)

pids = [1, 2, 3]
result = await Database.get_contents_by_pids(pids)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from enum import IntFlag
from typing import TYPE_CHECKING, Literal

import aiotieba.typing as aiotieba
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import DatabaseConfig
from src.core.controller import Controller
from src.models import Base, ContentModel, ForumModel, ProcessContextModel, ProcessLogModel, UserLevelModel, UserModel
from src.schemas.tieba import Comment, Content, Model2Content, Post, User
from src.utils.logging import system_logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable
    from datetime import datetime

    from src.core.config import SystemConfig
    from src.schemas.event import UpdateEventData

MixedContentType = aiotieba.Thread | Post | Comment


class UpdateStatus(IntFlag):
    """更新状态

    Note:
        NEW_WITH_CHILD: 包含子内容的新内容\n
        NEW: 新内容\n
        UPDATED: 有更新的内容\n
        UNCHANGED: 无变化的内容
        IS_NEW: 新内容（NEW | NEW_WITH_CHILD）\n
        IS_STABLE: 无子内容（UNCHANGED | NEW）\n
        HAS_CHANGES: 有变化的内容（UPDATED | NEW_WITH_CHILD）
    """

    NEW_WITH_CHILD = 1 << 0
    NEW = 1 << 1
    UPDATED = 1 << 2
    UNCHANGED = 1 << 3

    IS_NEW = NEW | NEW_WITH_CHILD
    IS_STABLE = UNCHANGED | NEW
    HAS_CHANGES = UPDATED | NEW_WITH_CHILD


class Database:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]

    @classmethod
    async def startup(cls, _: None = None) -> None:
        config = Controller.config
        system_logger.info("正在初始化数据库...")
        system_logger.info(f"数据库类型: {config.database.type}")
        database_config = DatabaseConfig.model_validate(config.database)
        cls.engine = create_async_engine(
            database_config.database_url,
            pool_pre_ping=(database_config.type != "sqlite"),
        )
        cls.sessionmaker = async_sessionmaker(cls.engine, class_=AsyncSession, expire_on_commit=False)
        async with cls.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        system_logger.info("数据库初始化完成")

    @classmethod
    async def teardown(cls, _: None = None) -> None:
        system_logger.info("正在关闭数据库连接...")
        await cls.engine.dispose()
        system_logger.info("数据库连接已关闭")

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
    async def update_config(cls, data: UpdateEventData[SystemConfig]):
        old_db = DatabaseConfig.model_validate(data.old.database)
        new_db = DatabaseConfig.model_validate(data.new.database)
        if old_db != new_db:
            system_logger.info("检测到数据库配置已更改，正在重新连接...")
            await cls.teardown()
            await cls.startup()

    @classmethod
    async def test_connection(cls, config: DatabaseConfig) -> tuple[bool, Exception | None]:
        """
        测试数据库连接。
        返回 (True, None) 表示连接成功，(False, 异常对象) 表示连接失败。
        """
        import asyncio

        try:
            config = DatabaseConfig.model_validate(config)
            test_engine = create_async_engine(
                config.database_url,
                pool_pre_ping=(config.type != "sqlite"),
            )
        except (ValueError, ValidationError):
            return False, ValueError("数据库配置无效")
        except Exception as e:
            return False, e

        async def _test():
            async with test_engine.connect() as conn:
                await conn.execute(select(1))

        try:
            await asyncio.wait_for(_test(), timeout=30)
            return True, None
        except TimeoutError:
            return False, TimeoutError("数据库连接测试超时（30秒）")
        except Exception as e:
            return False, e

    @classmethod
    async def save_items[
        T: (ContentModel, ForumModel, UserModel, ProcessLogModel, ProcessContextModel, UserLevelModel)
    ](
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

        stmt = pg_insert(model) if dialect == "postgresql" else sqlite_insert(model)

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

    @staticmethod
    def combine_models_to_content(
        content_model: ContentModel,
        user_model: UserModel | None,
        user_level_model: UserLevelModel | None,
    ) -> Content:
        """
        将 ContentModel、UserModel 和 UserLevelModel 组合为 Content 对象
        TODO 在 1.3.x 移除None的支持，强制要求提供 UserModel 和 UserLevelModel。
        """
        user = None
        if user_model and user_level_model:
            user = User(
                user_id=user_model.user_id,
                user_name=user_model.user_name,
                nick_name=user_model.nick_name,
                portrait=user_model.portrait,
                level=user_level_model.level,
            )
        else:
            user = User(user_id=0, user_name="", nick_name="", portrait="", level=0)
            system_logger.warning(
                f"ContentModel(pid={content_model.pid}) 缺少 UserModel 或 UserLevelModel，已使用默认 User 填充。"
            )

        formater = Model2Content.get(content_model.type)
        if not formater:
            raise ValueError(f"Unsupported content type: {content_model.type}")

        return formater(content_model, user)

    @classmethod
    async def get_full_contents_by_pids(cls, pids: Iterable[int]) -> list[Content]:
        pid_list = list(pids)
        if not pid_list:
            return []
        async with cls.get_session() as session:
            result = await session.execute(
                select(ContentModel, UserModel, UserLevelModel)
                .where(ContentModel.pid.in_(pid_list))
                .join(UserModel, ContentModel.author_id == UserModel.user_id, isouter=True)
                .join(
                    UserLevelModel,
                    (UserLevelModel.user_id == ContentModel.author_id) & (UserLevelModel.fname == ContentModel.fname),
                    isouter=True,
                )
            )
            return [cls.combine_models_to_content(model[0], model[1], model[2]) for model in result.all()]

    @classmethod
    async def get_full_content_by_pid(cls, pid: int) -> Content | None:
        async with cls.get_session() as session:
            result = await session.execute(
                select(ContentModel, UserModel, UserLevelModel)
                .where(ContentModel.pid == pid)
                .join(UserModel, ContentModel.author_id == UserModel.user_id, isouter=True)
                .join(
                    UserLevelModel,
                    (UserLevelModel.user_id == ContentModel.author_id) & (UserLevelModel.fname == ContentModel.fname),
                    isouter=True,
                )
            )
            row = result.first()
            if row is None:
                return None
            return cls.combine_models_to_content(row[0], row[1], row[2])

    @classmethod
    async def get_user_by_id(cls, user_id: int) -> UserModel | None:
        async with cls.get_session() as session:
            result = await session.execute(select(UserModel).where(UserModel.user_id == user_id))
            return result.scalars().first()

    @classmethod
    async def iter_all_contents(cls) -> AsyncGenerator[ContentModel, None]:
        async with cls.get_session() as session:
            result = await session.stream(select(ContentModel))
            async for row in result.scalars():
                yield row

    @classmethod
    async def check_and_update_cache(cls, content: MixedContentType) -> UpdateStatus:
        async with cls.get_session() as session:
            session.begin()
            result = await session.execute(
                select(ContentModel.last_time, ContentModel.reply_num).where(ContentModel.pid == content.pid)
            )
            row = result.first()
            content_cache = None if row is None else (row[0], row[1])
            await session.execute(
                update(ContentModel)
                .where(ContentModel.pid == content.pid)
                .values(last_time=getattr(content, "last_time", None), reply_num=getattr(content, "reply_num", None))
            )
            await session.commit()

        updated = UpdateStatus.UNCHANGED
        if isinstance(content, aiotieba.Thread):
            if content_cache is None:
                updated = UpdateStatus.NEW_WITH_CHILD if content.reply_num > 0 else UpdateStatus.NEW
            elif (content.last_time, content.reply_num) != content_cache:
                updated = UpdateStatus.UPDATED
        elif isinstance(content, Post):
            if content_cache is None:
                updated = UpdateStatus.NEW_WITH_CHILD if content.reply_num > 4 else UpdateStatus.NEW
            elif (None, content.reply_num) != content_cache:
                updated = UpdateStatus.UPDATED
        elif isinstance(content, Comment):
            if content_cache is None:
                updated = UpdateStatus.NEW

        return updated

    @classmethod
    async def clear_contents_before(cls, before: datetime) -> int:
        async with cls.get_session() as session:
            result = await session.execute(delete(ContentModel).where(ContentModel.last_update < before))
            await session.commit()
            return result.rowcount or 0
