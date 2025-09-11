import pytest

from src.util.event import AsyncEvent, EventListener
from src.util.logging import LogRecorder


@pytest.mark.asyncio
async def test_async_event_broadcast_logs_exception():
    # 重置 system 记录器缓存，避免受其他测试影响
    LogRecorder.messages["system"] = []

    event: AsyncEvent[str] = AsyncEvent()

    async def faulty_listener(data: str):
        raise ValueError("Listener error")

    event.on(faulty_listener)

    await event.broadcast("test")

    records = LogRecorder.get_records("system")
    assert records

    # 检查是否存在预期的异常日志
    assert any(
        r.record["level"].name == "ERROR" and "事件处理函数执行异常: Listener error" in r.record["message"]
        for r in records
    )


@pytest.mark.asyncio
async def test_async_event_calls_sync_and_async_listeners():
    LogRecorder.messages["system"] = []
    event: AsyncEvent[int] = AsyncEvent()

    called: list[str] = []

    async def al(v: int):
        called.append(f"a{v}")

    def sl(v: int):
        called.append(f"s{v}")

    event.on(al)
    event.on(sl)

    await event.broadcast(7)

    assert set(called) == {"a7", "s7"}
    # 无错误日志
    assert not any(r.record["level"].name == "ERROR" for r in LogRecorder.get_records("system"))


@pytest.mark.asyncio
async def test_async_event_unregister_removes_listener():
    LogRecorder.messages["system"] = []
    event: AsyncEvent[str] = AsyncEvent()

    calls: list[str] = []

    async def listener(data: str):
        calls.append(data)

    el: EventListener = event.on(listener)

    await event.broadcast("x")
    el.un_register()
    await event.broadcast("y")

    assert calls == ["x"]


@pytest.mark.asyncio
async def test_async_event_multiple_listeners_errors_are_logged_and_all_run():
    LogRecorder.messages["system"] = []
    event: AsyncEvent[str] = AsyncEvent()

    calls: list[str] = []

    async def ok(data: str):
        calls.append("ok")

    def bad_sync(data: str):
        raise RuntimeError("bad sync")

    async def bad_async(data: str):
        raise ValueError("bad async")

    event.on(ok)
    event.on(bad_sync)
    event.on(bad_async)

    await event.broadcast("t")

    # 所有监听器应均被调用，其中一个成功
    assert "ok" in calls

    # 两条异常日志应被记录（顺序不保证）
    msgs = [m.record["message"] for m in LogRecorder.get_records("system")]
    assert any("事件处理函数执行异常: bad sync" in m for m in msgs)
    assert any("事件处理函数执行异常: bad async" in m for m in msgs)


@pytest.mark.asyncio
async def test_async_event_accepts_eventlistener_param_and_registers_again():
    LogRecorder.messages["system"] = []
    event: AsyncEvent[int] = AsyncEvent()

    counter = {"n": 0}

    async def inc(v: int):
        counter["n"] += 1

    el = event.on(inc)
    # 使用 EventListener 再次注册相同函数
    event.on(el)

    await event.broadcast(1)

    # 应该被调用两次
    assert counter["n"] == 2


@pytest.mark.asyncio
async def test_async_event_broadcast_without_listeners_noop():
    event: AsyncEvent[None] = AsyncEvent()
    # 不应抛错
    await event.broadcast(None)
