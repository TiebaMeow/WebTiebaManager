import asyncio

from src.util.event import AsyncEvent
from src.util.logging import system_logger


async def test_async_event_broadcast_logs_exception():
    event = AsyncEvent()

    async def faulty_listener(data):
        raise ValueError("Listener error")

    event.on(faulty_listener)
    await event.broadcast("test")
    # 检查日志内容


asyncio.run(test_async_event_broadcast_logs_exception())
