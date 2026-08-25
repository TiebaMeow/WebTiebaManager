import sys
import types
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

from src.core.config import DatabaseConfig
from src.models import ContentModel
from src.schemas.tieba import Image

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


# 为模块设置属性
module.Controller = _DummyController  # type: ignore
sys.modules["src.control"] = module

import src.db.interface as dbi

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
    # 使用不重复的 pid 避免依赖删除
    items_none = [make_content(1000), make_content(1001)]
    # chunk_size=None
    await Database.save_items(items_none, on_conflict="ignore", chunk_size=None)
    got = await Database.get_contents_by_pids([1000, 1001])
    assert {c.pid for c in got} == {1000, 1001}

    # 使用新的 pid 测试 chunk_size<=0
    items_zero = [make_content(1002), make_content(1003)]
    await Database.save_items(items_zero, on_conflict="ignore", chunk_size=0)
    got2 = await Database.get_contents_by_pids([1002, 1003])
    assert {c.pid for c in got2} == {1002, 1003}


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


@pytest.mark.asyncio
async def test_mixed_model_raise_type_error():
    from src.models import ForumModel

    f = ForumModel(fname="f", fid=1)
    c = make_content(999)
    with pytest.raises(TypeError):
        # 混合模型类型应报错
        await Database.save_items([f, c])


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
    # create_time 不应被更新
    assert got.create_time == orig.create_time


@pytest.mark.asyncio
async def test_images_serialize_deserialize_non_empty(setup_db):
    # 插入包含 images 的内容，验证能自动序列化到 JSON 并在读取时反序列化为 Image 模型
    pid = 2201
    item = make_content(pid)
    item.images = [
        Image(hash="h1", width=10, height=20, src="http://x/1.jpg"),
        Image(hash="h2", width=30, height=40, src="http://x/2.jpg"),
    ]
    await Database.save_items([item], on_conflict="ignore")

    got = (await Database.get_contents_by_pids([pid]))[0]
    assert isinstance(got.images, list)
    assert len(got.images) == 2
    assert isinstance(got.images[0], Image)
    assert got.images[0].hash == "h1"
    assert isinstance(got.images[1], Image)
    assert got.images[1].src.endswith("2.jpg")


@pytest.mark.asyncio
async def test_upsert_updates_images_field(setup_db):
    # 先写入一条包含 1 张图片的记录
    pid = 2202
    base = make_content(pid)
    base.images = [Image(hash="h1", width=1, height=1, src="s1")]
    await Database.save_items([base], on_conflict="ignore")

    # upsert 更新为 2 张图片
    updated = make_content(pid)
    updated.images = [
        Image(hash="h2", width=2, height=2, src="s2"),
        Image(hash="h3", width=3, height=3, src="s3"),
    ]
    await Database.save_items([updated], on_conflict="upsert")

    got = (await Database.get_contents_by_pids([pid]))[0]
    assert [img.hash for img in got.images] == ["h2", "h3"]

    # 再次 upsert 但排除 images，不应改变现有 images
    updated2 = make_content(pid)
    updated2.images = [Image(hash="h4", width=4, height=4, src="s4")]
    await Database.save_items([updated2], on_conflict="upsert", exclude_columns=["images"])
    got2 = (await Database.get_contents_by_pids([pid]))[0]
    assert [img.hash for img in got2.images] == ["h2", "h3"]


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

    # 不再测试删除（方法已移除）


@pytest.mark.asyncio
async def test_is_updated_post_and_comment(setup_db):
    import src.schemas.tieba as tieba

    now_ts = int(datetime.now(SH_TZ).timestamp())
    user = tieba.User(user_name="u", nick_name="n", user_id=98765, portrait="p", level=1)

    # 1) Post
    post_new = tieba.Post(
        fname="f1",
        title="t1",
        text="x",
        images=[],
        create_time=now_ts,
        tid=3001,
        pid=3001,
        floor=1,
        reply_num=4,
        user=user,
    )
    st1 = await Database.check_and_update_cache(post_new)
    assert st1 == dbi.UpdateStatus.NEW
    assert st1 & dbi.UpdateStatus.IS_NEW
    assert st1 & dbi.UpdateStatus.IS_STABLE

    post_new_child = tieba.Post(
        fname="f1",
        title="t1",
        text="x",
        images=[],
        create_time=now_ts,
        tid=3002,
        pid=3002,
        floor=1,
        reply_num=5,
        user=user,
    )
    st2 = await Database.check_and_update_cache(post_new_child)
    assert st2 == dbi.UpdateStatus.NEW_WITH_CHILD
    assert st2 & dbi.UpdateStatus.IS_NEW
    assert st2 & dbi.UpdateStatus.HAS_CHANGES

    await Database.save_items([ContentModel.from_content(post_new_child)])

    post_new_child.reply_num = 10
    st3 = await Database.check_and_update_cache(post_new_child)
    assert st3 == dbi.UpdateStatus.UPDATED
    assert st3 & dbi.UpdateStatus.HAS_CHANGES

    st4 = await Database.check_and_update_cache(post_new_child)
    assert st4 == dbi.UpdateStatus.UNCHANGED
    assert st4 & dbi.UpdateStatus.IS_STABLE

    # 2) Comment
    comment_new = tieba.Comment(
        fname="f2",
        title="t2",
        text="c",
        images=[],
        create_time=now_ts,
        tid=4001,
        pid=4001,
        floor=2,
        user=user,
    )
    st5 = await Database.check_and_update_cache(comment_new)
    assert st5 == dbi.UpdateStatus.NEW


@pytest.mark.asyncio
async def test_clear_contents_before(setup_db):
    # 构造三条记录，last_update 分别在过去 2 天、1 天和现在
    now_dt = datetime.now(SH_TZ)
    old_dt = now_dt - timedelta(days=2)
    mid_dt = now_dt - timedelta(days=1)
    new_dt = now_dt

    a = make_content(5001)
    a.last_update = old_dt
    b = make_content(5002)
    b.last_update = mid_dt
    c = make_content(5003)
    c.last_update = new_dt
    await Database.save_items([a, b, c], on_conflict="ignore")

    # 阈值设为 1.5 天前，只应删除 a
    threshold = now_dt - timedelta(days=1, hours=12)
    deleted = await Database.clear_contents_before(threshold)
    assert deleted >= 1
    got = await Database.get_contents_by_pids([5001, 5002, 5003])
    left = {x.pid for x in got}
    assert 5001 not in left
    assert {5002, 5003}.issubset(left)


@pytest.mark.asyncio
async def test_check_and_update_cache_many(setup_db):
    # P2-4: 批量检查/更新缓存，状态与输入顺序一致
    import src.schemas.tieba as tieba

    now_ts = int(datetime.now(SH_TZ).timestamp())
    user = tieba.User(user_name="u", nick_name="n", user_id=98765, portrait="p", level=1)

    post_new = tieba.Post(
        fname="f1",
        title="t1",
        text="x",
        images=[],
        create_time=now_ts,
        tid=6001,
        pid=6001,
        floor=1,
        reply_num=4,
        user=user,
    )
    comment_new = tieba.Comment(
        fname="f2",
        title="t2",
        text="c",
        images=[],
        create_time=now_ts,
        tid=6002,
        pid=6002,
        floor=2,
        user=user,
    )
    thread_new = tieba.Thread(
        fname="f3",
        title="t3",
        text="x",
        images=[],
        create_time=now_ts,
        tid=6003,
        pid=6003,
        floor=1,
        last_time=now_ts,
        reply_num=3,
        user=user,
    )

    # 全部为新内容：post reply_num=4 -> NEW，comment -> NEW，thread reply_num=3 -> NEW_WITH_CHILD
    statuses = await Database.check_and_update_cache_many([post_new, comment_new, thread_new])
    assert statuses == [dbi.UpdateStatus.NEW, dbi.UpdateStatus.NEW, dbi.UpdateStatus.NEW_WITH_CHILD]

    await Database.save_items(
        [ContentModel.from_content(post_new), ContentModel.from_content(thread_new)],
        on_conflict="ignore",
    )

    # 已入库且无变化 -> UNCHANGED；reply_num 变化 -> UPDATED；comment 仍未入库 -> NEW
    post_new.reply_num = 8
    statuses2 = await Database.check_and_update_cache_many([post_new, comment_new])
    assert statuses2 == [dbi.UpdateStatus.UPDATED, dbi.UpdateStatus.NEW]

    # 缓存已被批量更新为最新值
    got = await Database.get_contents_by_pids([6001])
    assert got[0].reply_num == 8

    # 批量内同 pid 重复：后项覆盖前项（首项相对缓存 8 无变化，次项 12 为 UPDATED）
    post_later = post_new.model_copy(update={"reply_num": 12})
    statuses3 = await Database.check_and_update_cache_many([post_new, post_later])
    assert statuses3 == [dbi.UpdateStatus.UNCHANGED, dbi.UpdateStatus.UPDATED]
    got2 = await Database.get_contents_by_pids([6001])
    assert got2[0].reply_num == 12


@pytest.mark.asyncio
async def test_flush_content_buffer_broadcast_order_and_failure(setup_db, monkeypatch):
    # P2-4: 整 chunk 提交成功后才按原顺序广播；保存异常时该 chunk 不被广播
    import src.schemas.tieba as tieba
    from src.core.controller import Controller
    from src.schemas.process import ProcessObject
    from src.tieba.crawler import Crawler

    now_ts = int(datetime.now(SH_TZ).timestamp())
    user = tieba.User(user_name="u", nick_name="n", user_id=12345, portrait="p", level=1)

    def make_post(pid):
        return tieba.Post(
            fname="f1",
            title=f"t-{pid}",
            text="x",
            images=[],
            create_time=now_ts,
            tid=7000,
            pid=pid,
            floor=pid,
            reply_num=4,
            user=user,
        )

    buffers = [(ProcessObject(content=make_post(pid)), ContentModel.from_content(make_post(pid))) for pid in (7001, 7002)]

    # 广播处理器在广播时查询数据库：对应 chunk 的全部内容必须已经提交
    seen: list[int] = []
    broadcast_db_snapshots: list[set[int]] = []

    async def spy(process_object):
        items = await Database.get_contents_by_pids([7001, 7002])
        broadcast_db_snapshots.append({i.pid for i in items})
        seen.append(process_object.content.pid)

    listener = Controller.DispatchContent.on(spy)
    try:
        await Crawler._flush_content_buffer(buffers)
    finally:
        listener.un_register()

    # 按原抓取顺序广播，且每次广播时 chunk 内容已全部入库
    assert seen == [7001, 7002]
    assert broadcast_db_snapshots == [{7001, 7002}, {7001, 7002}]
    assert {i.pid for i in await Database.get_contents_by_pids([7001, 7002])} == {7001, 7002}

    # 数据库保存失败：不得广播该 chunk
    async def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(Database, "save_items", boom)
    seen2: list[int] = []
    listener2 = Controller.DispatchContent.on(lambda obj: seen2.append(obj.content.pid))
    try:
        await Crawler._flush_content_buffer(buffers)
    finally:
        listener2.un_register()
    assert seen2 == []


@pytest.mark.asyncio
async def test_overview_sql_aggregation(setup_db):
    # P2-5: 概览统计聚合结果与旧逻辑一致（total/hit/whitelist/hint + 用户隔离 + 24h 边界）
    from datetime import datetime, timedelta

    from src.api.routes.process import get_overview
    from src.models import ProcessLogModel

    now = datetime.now()
    rows = [
        ProcessLogModel(
            tid=1, pid=1001, user="alice", create_time=now, process_time=now - timedelta(hours=1),
            result_rule="ruleA", is_whitelist=True,
        ),
        ProcessLogModel(
            tid=1, pid=1002, user="alice", create_time=now, process_time=now - timedelta(hours=2),
            result_rule="ruleA", is_whitelist=True,
        ),
        ProcessLogModel(
            tid=2, pid=2001, user="alice", create_time=now, process_time=now - timedelta(hours=3),
            result_rule="ruleB", is_whitelist=False,
        ),
        ProcessLogModel(
            tid=2, pid=2002, user="alice", create_time=now, process_time=now - timedelta(hours=4),
            result_rule="ruleB", is_whitelist=False,
        ),
        ProcessLogModel(
            tid=2, pid=2003, user="alice", create_time=now, process_time=now - timedelta(hours=5),
            result_rule="ruleB", is_whitelist=False,
        ),
        ProcessLogModel(
            tid=1, pid=1003, user="alice", create_time=now, process_time=now - timedelta(hours=7),
            result_rule="ruleA", is_whitelist=False,
        ),
        # 超过 24h：不计入 total，但仍出现在 hint_rules
        ProcessLogModel(
            tid=4, pid=4001, user="alice", create_time=now, process_time=now - timedelta(hours=30),
            result_rule="oldRule", is_whitelist=False,
        ),
        # 其他用户：不应计入
        ProcessLogModel(
            tid=5, pid=5001, user="bob", create_time=now, process_time=now - timedelta(hours=1),
            result_rule="ruleBob", is_whitelist=False,
        ),
    ]
    await Database.save_items(rows, on_conflict="ignore")

    # 未匹配规则的日志（result_rule/is_whitelist 均为 None）：save_items 会跳过 None 值，用 session 插入
    no_match = ProcessLogModel(
        tid=3, pid=3001, user="alice", create_time=now, process_time=now - timedelta(hours=6),
        result_rule=None, is_whitelist=None,
    )
    async with Database.get_session() as session:
        session.add(no_match)
        await session.commit()

    resp = await get_overview(types.SimpleNamespace(username="alice"))
    data = resp.data
    assert data.total == {"all": 7, "hit": 4, "whitelist": 2}
    assert data.hit_rules == {"ruleB": 3, "ruleA": 1}
    assert data.whitelist_rules == {"ruleA": 2}
    assert set(data.hint_rules) == {"ruleA", "ruleB", "oldRule"}


@pytest.mark.asyncio
async def test_shanghai_tz_semantics(setup_db):
    # P2-8: SQLite 读回的 datetime 带上海时区语义，Unix 时间戳不再按服务器本地时区解释
    from datetime import datetime

    from src.models.models import SHANGHAI_TZ, now_with_tz

    t0 = now_with_tz()
    item = make_content(8001)
    item.create_time = t0
    item.last_update = t0
    await Database.save_items([item], on_conflict="ignore")

    got = (await Database.get_contents_by_pids([8001]))[0]
    # 读回必须带上海时区语义（+08:00）
    assert got.create_time.tzinfo is not None
    assert got.create_time.utcoffset() == timedelta(hours=8)
    assert got.last_update.utcoffset() == timedelta(hours=8)
    # 同一时刻：时间戳一致（序列化不再按服务器本地时区解释）
    assert got.create_time.timestamp() == pytest.approx(t0.timestamp())
    assert got.last_update.timestamp() == pytest.approx(t0.timestamp())

    # naive datetime 写入按上海时区解释（墙钟时刻不变）
    naive = datetime(2026, 1, 2, 3, 4, 5)
    item2 = make_content(8002)
    item2.create_time = naive
    await Database.save_items([item2], on_conflict="ignore")
    got2 = (await Database.get_contents_by_pids([8002]))[0]
    assert got2.create_time.tzinfo is not None
    assert got2.create_time.replace(tzinfo=None) == naive
    assert got2.create_time.utcoffset() == timedelta(hours=8)

    # ProcessLogModel.process_time 同样带上海时区语义
    from src.models import ProcessLogModel

    log = ProcessLogModel(tid=9, pid=9001, user="tzuser", create_time=t0, process_time=t0)
    async with Database.get_session() as session:
        session.add(log)
        await session.commit()

    async with Database.get_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(ProcessLogModel).where(ProcessLogModel.pid == 9001))
        got_log = result.scalars().first()
    assert got_log is not None
    assert got_log.create_time.utcoffset() == timedelta(hours=8)
    assert got_log.process_time.utcoffset() == timedelta(hours=8)
    assert got_log.process_time.timestamp() == pytest.approx(t0.timestamp())


class _RecordingEngineProxy:
    """包装真实引擎，记录 dispose 调用（用于断言连接池被释放）。"""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "dispose_called", False)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_real"), name)

    async def dispose(self):
        object.__setattr__(self, "dispose_called", True)
        await object.__getattribute__(self, "_real").dispose()


@pytest.mark.asyncio
async def test_test_connection_disposes_engine(monkeypatch, tmp_path):
    # P2-1: test_connection 结束后必须释放测试连接池
    created: list[_RecordingEngineProxy] = []
    real_create = dbi.create_async_engine

    def recording_create(*args, **kwargs):
        proxy = _RecordingEngineProxy(real_create(*args, **kwargs))
        created.append(proxy)
        return proxy

    monkeypatch.setattr(dbi, "create_async_engine", recording_create)

    # 成功路径：返回后引擎已 dispose
    ok_cfg = DatabaseConfig(type="sqlite", path=str(tmp_path / "conn_ok.db"))
    success, err = await Database.test_connection(ok_cfg)
    assert success is True
    assert err is None
    assert len(created) == 1
    assert created[0].dispose_called

    # 失败路径（目标为一个目录，无法打开数据库）：异常返回后同样已 dispose
    bad_cfg = DatabaseConfig(type="sqlite", path=str(tmp_path))
    success2, err2 = await Database.test_connection(bad_cfg)
    assert success2 is False
    assert err2 is not None
    assert len(created) == 2
    assert created[1].dispose_called
