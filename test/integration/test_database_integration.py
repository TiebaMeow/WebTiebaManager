import types

import pytest

# 注入一个最小化的 src.control 以避免导入时的循环依赖
module = types.ModuleType("src.control")


class _DummyEvent:
    def on(self, *_args, **_kwargs):
        return None


class _DummyController:
    Start = _DummyEvent()
    Stop = _DummyEvent()
    SystemConfigChange = _DummyEvent()
    DispatchContent = _DummyEvent()
    config = None

    @classmethod
    async def start(cls):
        return None

    @classmethod
    async def stop(cls):
        return None


module.Controller = _DummyController  # type: ignore
import sys

sys.modules["src.control"] = module

from datetime import datetime
from zoneinfo import ZoneInfo

import src.db.interface as dbi
from src.core.config import DatabaseConfig
from src.models import ContentModel

Database = dbi.Database

SH_TZ = ZoneInfo("Asia/Shanghai")


def make_content(pid: int, *, tid: int = 1000, fname: str = "test_forum", floor: int = 1, ctype: str = "post"):
    return ContentModel(
        pid=pid,
        tid=tid,
        fname=fname,
        create_time=datetime.now(SH_TZ),
        title=f"title-{pid}",
        text=f"text-{pid}",
        floor=floor,
        images=[],
        type=ctype,
        author_id=123456,
    )


@pytest.mark.skipif("RUN_DB_INTEGRATION" not in __import__("os").environ, reason="integration only")
@pytest.mark.asyncio
async def test_pg_integration(tmp_path_factory):
    import os

    # 保护现场：保存当前（由模块级 fixture 建立的）配置与引擎/会话工厂，
    # 以免下面的集成测试污染后续用例的运行环境。
    orig_config = getattr(dbi.Controller, "config", None)  # type: ignore
    orig_engine = getattr(Database, "engine", None)
    orig_sessionmaker = getattr(Database, "sessionmaker", None)

    try:
        # PostgreSQL
        pg_cfg = DatabaseConfig(
            type="postgresql",
            username=os.environ["PG_USER"],
            password=os.environ["PG_PASSWORD"],
            host=os.environ["PG_HOST"],
            port=int(os.environ["PG_PORT"]),
            db=os.environ["PG_DB"],
        )
        dbi.Controller.config = types.SimpleNamespace(database=pg_cfg)  # type: ignore
        await Database.startup()
        await Database.save_items([make_content(4001)], on_conflict="upsert")
        got = await Database.get_contents_by_pids([4001])
        assert got
        assert got[0].pid == 4001
        await Database.teardown()
    finally:
        # 恢复现场：还原到原始环境，保证后续测试继续使用原连接与数据。
        if orig_config is not None:
            dbi.Controller.config = orig_config  # type: ignore
        if orig_engine is not None:
            Database.engine = orig_engine
        if orig_sessionmaker is not None:
            Database.sessionmaker = orig_sessionmaker
