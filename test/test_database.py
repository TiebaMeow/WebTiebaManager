import asyncio
import sys
import types
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

from core.db.config import DatabaseConfig
from core.db.models import ContentModel

# 注入一个最小化的 core.control 以避免导入时的循环依赖
module = types.ModuleType("core.control")


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


# 为模块设置属性
module.Controller = _DummyController  # type: ignore
sys.modules["core.control"] = module

import core.db.interface as dbi  # noqa: E402

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


class _FakeSystemConfig:
    database: DatabaseConfig


@pytest_asyncio.fixture(scope="module")
async def setup_db(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("db")
    db_path = db_dir / "test.db"
    # 配置使用临时sqlite数据库到我们注入的 Dummy Controller 上
    cfg = _FakeSystemConfig()
    cfg.database = DatabaseConfig(type="sqlite", path=str(db_path))
    dbi.Controller.config = cfg  # type: ignore
    await Database.startup()
    try:
        yield
    finally:
        await Database.teardown()


@pytest.mark.asyncio
async def test_save_and_get_ignore(setup_db):
    items = [make_content(pid) for pid in (1, 2, 3)]
    await Database.save_items(items, on_conflict="ignore", chunk_size=2)

    got = await Database.get_contents_by_pids([1, 2, 3])
    got_pids = {c.pid for c in got}
    assert got_pids == {1, 2, 3}

    # 再次以 ignore 插入，不应报错且不应产生重复
    await Database.save_items(items, on_conflict="ignore")
    got2 = await Database.get_contents_by_pids([1, 2, 3])
    assert {c.pid for c in got2} == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_save_items_empty(setup_db):
        # 空列表不应报错
        await Database.save_items([], on_conflict="ignore")

    @pytest.mark.asyncio
    async def test_save_items_chunk_none_or_nonpositive(setup_db):
        items = [make_content(100), make_content(101)]
        await Database.delete_contents_by_pids([100, 101])
        # chunk_size=None
        await Database.save_items(items, on_conflict="ignore", chunk_size=None)
        got = await Database.get_contents_by_pids([100, 101])
        assert {c.pid for c in got} == {100, 101}
        # 再清理
        await Database.delete_contents_by_pids([100, 101])
        # chunk_size<=0
        await Database.save_items(items, on_conflict="ignore", chunk_size=0)
        got = await Database.get_contents_by_pids([100, 101])
        assert {c.pid for c in got} == {100, 101}

    @pytest.mark.asyncio
    async def test_upsert_with_exclude_all_nonpk_no_update(setup_db):
        # exclude 所有非主键列 -> 回退为 ignore，不应改变已有值
        updated = make_content(1)
        updated.text = "should-not-change"
        # 列出所有非主键列（与模型保持一致）
        exclude_cols = [
            "tid",
            "fname",
            "create_time",
            "title",
            "text",
            "floor",
            "images",
            "type",
            "author_id",
        ]
        await Database.save_items([updated], on_conflict="upsert", exclude_columns=exclude_cols)
        got = (await Database.get_contents_by_pids([1]))[0]
        assert got.text != "should-not-change"

    def test_mixed_model_raise_type_error():
        from core.db.models import ForumModel

        f = ForumModel(fname="f", fid=1)
        c = make_content(999)
        with pytest.raises(TypeError):
            # 混合模型类型应报错
            asyncio.get_event_loop().run_until_complete(Database.save_items([f, c]))  # type: ignore

    @pytest.mark.skipif("RUN_DB_INTEGRATION" not in __import__("os").environ, reason="integration only")
    @pytest.mark.asyncio
    async def test_mysql_and_pg_integration(tmp_path_factory):
        import os

        from core.db.config import DatabaseConfig

        # MySQL
        mysql_cfg = DatabaseConfig(
            type="mysql",
            username=os.environ["MYSQL_USER"],
            password=os.environ["MYSQL_PASSWORD"],
            host=os.environ["MYSQL_HOST"],
            port=int(os.environ["MYSQL_PORT"]),
            db=os.environ["MYSQL_DB"],
        )
        dbi.Controller.config = types.SimpleNamespace(database=mysql_cfg)  # type: ignore
        await Database.startup()
        await Database.save_items([make_content(3001)], on_conflict="upsert")
        got = await Database.get_contents_by_pids([3001])
        assert got
        assert got[0].pid == 3001
        await Database.teardown()

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


@pytest.mark.asyncio
async def test_upsert_updates_selected_columns(setup_db):
    # 先取一个已有内容并尝试更新
    orig = (await Database.get_contents_by_pids([1]))[0]

    # 修改text与floor，并尝试更改create_time（应被exclude_columns保护）
    new_ct = orig.create_time + timedelta(days=1)
    updated = make_content(1)
    updated.text = "updated-text"
    updated.floor = orig.floor + 1
    updated.create_time = new_ct

    await Database.save_items([updated], on_conflict="upsert", exclude_columns=["create_time"])

    got = (await Database.get_contents_by_pids([1]))[0]
    assert got.text == "updated-text"
    assert got.floor == orig.floor + 1
    # create_time 未应被更新
    assert got.create_time == orig.create_time


@pytest.mark.asyncio
async def test_get_thread_by_tid(setup_db):
    # 为新的tid插入一个post和一个thread
    tid = 2222
    post = make_content(10, tid=tid, ctype="post")
    thread = make_content(11, tid=tid, ctype="thread", floor=1)
    await Database.save_items([post, thread], on_conflict="ignore")

    got = await Database.get_thread_by_tid(tid)
    assert got is not None
    assert got.type == "thread"
    assert got.tid == tid
    assert got.pid == 11


@pytest.mark.asyncio
async def test_iter_all_and_delete(setup_db):
    # 迭代应能拿到至少我们插入的若干条
    seen_pids = set()
    async for row in Database.iter_all_contents():
        seen_pids.add(row.pid)
    assert {1, 2, 3, 10, 11}.issubset(seen_pids)

    # 删除两条并确认
    await Database.delete_contents_by_pids([2, 3])
    got = await Database.get_contents_by_pids([2, 3])
    assert got == []
