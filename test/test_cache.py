import asyncio
import sys
import types

import pytest

# 先注入一个最小可用的 src.control，避免真实依赖及循环导入
module = types.ModuleType("src.control")


class _DummyEvent:
    def on(self, *_args, **_kwargs):
        # 返回一个带有 un_register 的对象以模拟真实监听器
        class _L:
            def __init__(self, fn=None):
                self.fn = fn

            def un_register(self):
                return None

        return _L()


class _DummyController:
    Start = _DummyEvent()
    Stop = _DummyEvent()
    SystemConfigChange = _DummyEvent()
    DispatchContent = _DummyEvent()
    config = types.SimpleNamespace(cleanup_time="04:00")


module.Controller = _DummyController  # type: ignore
sys.modules["src.control"] = module

import src.util.cache as cache  # noqa: E402


@pytest.mark.asyncio
async def test_expire_cache_memory_basic(tmp_path):
    c = cache.ExpireCache(directory=None, expire_time=10)
    try:
        await c.set("k1", "v1")
        assert await c.get("k1") == "v1"

        vals = await c.values()
        assert "v1" in vals

        deleted = await c.delete("k1")
        assert deleted is True
        assert await c.get("k1") is None
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_expire_cache_expire_and_clear_event():
    c = cache.ExpireCache(directory=None, expire_time=1)
    try:
        await c.set("exp", "v")
        # 等待过期
        await asyncio.sleep(1.2)
        # 触发全局清理事件
        await cache.ClearCache.broadcast(None)
        # 过期后取值应为空
        assert await c.get("exp") is None
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_set_expire_time_delete_when_zero():
    c = cache.ExpireCache(directory=None, expire_time=10)
    try:
        await c.set("k", "v")
        # 将全局默认过期时间改为 0，会导致现有条目被删除
        await c.set_expire_time(0)
        assert await c.get("k") is None
    finally:
        await c.stop()


@pytest.mark.asyncio
async def test_unlimited_expire_unchanged():
    # expire_time=None -> 新增键为无限期
    c = cache.ExpireCache(directory=None, expire_time=None)
    try:
        await c.set("ku", "vu")
        # 提升到 10 秒，已有无限期键应保持无限期
        await c.set_expire_time(10)
        exp = await c.cache.get_expire("ku")
        assert exp == cache.UNLIMITED
    finally:
        await c.stop()


class DummyScheduler:
    def __init__(self):
        self.jobs = []
        self.running = False

    def add_job(self, func, trigger, id, replace_existing, executor, misfire_grace_time):  # noqa: A002
        self.jobs.append({
            "func": func,
            "trigger": trigger,
            "id": id,
            "replace_existing": replace_existing,
            "executor": executor,
            "misfire_grace_time": misfire_grace_time,
        })

    def start(self):
        self.running = True

    def shutdown(self):
        self.running = False


def test_cache_cleaner_start_update_stop(monkeypatch):
    # 替换为 DummyScheduler
    monkeypatch.setattr(cache, "AsyncIOScheduler", DummyScheduler)

    # 确保初始状态
    cache.CacheCleaner._clear_cache_scheduler = None
    cache.CacheCleaner._clear_cache_time = "04:00"
    cache.Controller.config.cleanup_time = "04:00"

    # start 会创建 scheduler，注册 job，并启动
    cache.CacheCleaner.start()
    sched = cache.CacheCleaner._clear_cache_scheduler
    assert isinstance(sched, DummyScheduler)
    assert sched.running is True
    assert len(sched.jobs) == 1

    # 修改配置时间并触发 update，应追加或替换任务（这里记录追加调用）
    cache.Controller.config.cleanup_time = "05:30"
    cache.CacheCleaner.update_clear_cache_time()
    assert cache.CacheCleaner._clear_cache_time == "05:30"
    assert len(sched.jobs) == 2

    # stop 停止调度器
    cache.CacheCleaner.stop()
    assert sched.running is False
