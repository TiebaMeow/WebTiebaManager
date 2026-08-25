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

import src.utils.cache as cache


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

    def shutdown(self, wait=True):  # noqa: A002
        self.running = False


def test_cache_cleaner_start_update_stop(monkeypatch):
    # 替换为 DummyScheduler
    monkeypatch.setattr(cache, "AsyncIOScheduler", DummyScheduler)
    cache.Controller.initialize()

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

    # stop 停止调度器，并置空以便下次 start 重建
    cache.CacheCleaner.stop()
    assert sched.running is False
    assert cache.CacheCleaner._clear_cache_scheduler is None


def test_cache_cleaner_restart_boundary(monkeypatch):
    # P2-3: 连续 start / 停止后再启动均不炸，且重建新实例只注册一个 clear_cache_job
    monkeypatch.setattr(cache, "AsyncIOScheduler", DummyScheduler)
    cache.CacheCleaner._clear_cache_scheduler = None
    cache.CacheCleaner._clear_cache_time = "04:00"

    cache.CacheCleaner.start()
    first = cache.CacheCleaner._clear_cache_scheduler
    cache.CacheCleaner.start()
    second = cache.CacheCleaner._clear_cache_scheduler
    assert second is not first
    assert second.running is True
    assert len(second.jobs) == 1

    cache.CacheCleaner.stop()
    assert cache.CacheCleaner._clear_cache_scheduler is None
    cache.CacheCleaner.start()
    third = cache.CacheCleaner._clear_cache_scheduler
    assert third is not first
    assert third is not second
    assert third.running is True
    assert len(third.jobs) == 1


def test_cache_cleaner_invalid_cleanup_time(monkeypatch):
    # P2-3: 非法清理时间不注册任务且有告警日志
    from loguru import logger

    monkeypatch.setattr(cache, "AsyncIOScheduler", DummyScheduler)
    cache.CacheCleaner._clear_cache_scheduler = None
    cache.CacheCleaner._clear_cache_time = "25:99"

    records: list[str] = []

    def sink_fn(message):
        records.append(str(message))

    sink_id = logger.add(sink_fn, level="ERROR")
    try:
        cache.CacheCleaner.start()
    finally:
        logger.remove(sink_id)

    sched = cache.CacheCleaner._clear_cache_scheduler
    assert isinstance(sched, DummyScheduler)
    assert len(sched.jobs) == 0
    assert any("清理时间配置无效" in r for r in records)


def test_cache_cleaner_update_invalid_time_keeps_old_job(monkeypatch):
    # P2-3: update 收到非法值（如 "25:99"）时保持旧清理时间与旧调度任务
    from loguru import logger

    monkeypatch.setattr(cache, "AsyncIOScheduler", DummyScheduler)
    cache.CacheCleaner._clear_cache_scheduler = None
    cache.CacheCleaner._clear_cache_time = "04:00"
    cache.CacheCleaner.start()
    sched = cache.CacheCleaner._clear_cache_scheduler
    assert len(sched.jobs) == 1

    records: list[str] = []

    def sink_fn(message):
        records.append(str(message))

    sink_id = logger.add(sink_fn, level="ERROR")
    try:
        cache.Controller.config.cleanup_time = "25:99"
        cache.CacheCleaner.update_clear_cache_time()
    finally:
        logger.remove(sink_id)

    assert cache.CacheCleaner._clear_cache_time == "04:00"
    assert len(sched.jobs) == 1
    assert any("清理时间配置无效" in r for r in records)


def test_system_config_rejects_invalid_cleanup_time():
    # P2-3: 非法 HH:MM 在模型校验阶段被拒绝，避免无效配置先写盘
    from pydantic import ValidationError

    from src.core.config import SystemConfig

    with pytest.raises(ValidationError):
        SystemConfig(cleanup_time="25:99")
    with pytest.raises(ValidationError):
        SystemConfig(cleanup_time="foo")
    assert SystemConfig(cleanup_time="04:30").cleanup_time == "04:30"
