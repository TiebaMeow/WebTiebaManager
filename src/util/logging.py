from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, NamedTuple

from loguru import logger

from .event import AsyncEvent

from src.constance import BASE_DIR

if TYPE_CHECKING:
    from loguru import Message, Record


class LogEventData(NamedTuple):
    name: str | None
    message: Message


LogEvent = AsyncEvent[LogEventData]()


def try_broadcast_log(message: Message):
    try:
        name = message.record["extra"].get("name")
        asyncio.get_running_loop().create_task(LogEvent.broadcast(LogEventData(name, message)))
    except RuntimeError:
        # 没有事件循环在运行
        pass


class LogRecorder:
    MAX_LINES = 100
    messages: dict[str, list[Message]] = {}

    @classmethod
    def add(cls, name: str):
        if name not in cls.messages:
            cls.messages[name] = []

    @classmethod
    def remove(cls, name: str):
        if name in cls.messages:
            del cls.messages[name]

    @classmethod
    def sink(cls, message: Message):
        name = message.record["extra"].get("name")

        if name is None or name not in cls.messages:
            return

        cls.messages[name].append(message)
        # 限制最大行数
        if len(cls.messages[name]) > cls.MAX_LINES:
            cls.messages[name] = cls.messages[name][-cls.MAX_LINES :]

    @classmethod
    def get_records(cls, name: str) -> list[Message]:
        return cls.messages.get(name, [])


# 移除默认处理器
logger.remove()

# 自定义格式
log_format = "{time:YYYY-MM-DD HH:mm:ss,SSS} [{level}] | {extra[name]} | {message}"

logger.add(try_broadcast_log, format=log_format, level="DEBUG")

logger.add(LogRecorder.sink, format=log_format, level="DEBUG")


# 控制台过滤器：name=="system" 或者 error级别的日志
def console_filter(record: Record):
    return record["extra"].get("name") == "system" or record["level"].no >= logger.level("ERROR").no


logger.add(sys.stdout, format=log_format, filter=console_filter, level="DEBUG")

# 修改文件处理器：输出到 logos 文件夹下
logger.add(
    BASE_DIR / "logs" / "webtm_{time:YYYY-MM-DD}.log",
    format=log_format,
    rotation="00:00",
    retention="1 month",
    level="DEBUG",
)

LogRecorder.add("system")
system_logger = logger.bind(name="system")
