import asyncio
import sys
import types
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio

from src.db import ContentModel, DatabaseConfig, Image

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


def test_mixed_model_raise_type_error():
    from src.db import ForumModel

    f = ForumModel(fname="f", fid=1)
    c = make_content(999)
    with pytest.raises(TypeError):
        # 混合模型类型应报错
        asyncio.get_event_loop().run_until_complete(Database.save_items([f, c]))  # type: ignore


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
    import src.typedef as typedef

    now_ts = int(datetime.now(SH_TZ).timestamp())
    user = typedef.User(user_name="u", nick_name="n", user_id=98765, portrait="p", level=1)

    # 1) Post
    post_new = typedef.Post(
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

    post_new_child = typedef.Post(
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
    comment_new = typedef.Comment(
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
