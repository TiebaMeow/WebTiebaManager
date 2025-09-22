from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, NamedTuple

from aiotieba.logging import set_formatter
from loguru import logger

from src.core.constants import BASE_DIR, DEBUG, DEV

from .event import AsyncEvent

if TYPE_CHECKING:
    from loguru import Message, Record

set_formatter(
    logging.Formatter("{asctime} [{levelname}] | aiotieba.{funcName} | {message}", "%Y-%m-%d %H:%M:%S", style="{")
)


class LogEventData(NamedTuple):
    name: str | None
    message: Message


LogEvent = AsyncEvent[LogEventData]()


LOG_LEVEL = "DEBUG" if DEBUG else os.getenv("WEBTM_LOG_LEVEL", "INFO").upper()
LOG_DIR = BASE_DIR / "logs"
JSON_LOG_DIR = LOG_DIR / "json"


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
log_format = "{time:YYYY-MM-DD HH:mm:ss} [{level}] | {extra[name]} | {message}"

logger.add(try_broadcast_log, format=log_format, level=LOG_LEVEL)

logger.add(LogRecorder.sink, format=log_format, level=LOG_LEVEL)


# 只在开发模式或调试模式下输出所有日志，否则只输出 system 日志和错误以上级别的日志
def console_filter(record: Record):
    if DEV or DEBUG:
        return True
    return record["extra"].get("name") == "system" or record["level"].no >= logger.level("ERROR").no


logger.add(sys.stdout, format=log_format, filter=console_filter, level=LOG_LEVEL)

# 修改文件处理器：输出到 logos 文件夹下
logger.add(
    LOG_DIR / "webtm_{time:YYYY-MM-DD}.log",
    format=log_format,
    rotation="00:00",
    retention="1 month",
    level=LOG_LEVEL,
)

logger.add(
    JSON_LOG_DIR / "webtm_{time:YYYY-MM-DD}.json",
    format=log_format,
    rotation="00:00",
    retention="1 month",
    level=LOG_LEVEL,
    serialize=True,
)

LogRecorder.add("system")
system_logger = logger.bind(name="system")


@contextmanager
def exception_logger(
    message: str | None = None,
    /,
    logger=system_logger,
    reraise: bool = False,
    ignore_exceptions: tuple[type[Exception], ...] | None = None,
):
    try:
        yield
    except Exception as exc:
        if ignore_exceptions and isinstance(exc, ignore_exceptions):
            return
        if message:
            logger.exception(f"{message}: {exc}")
        else:
            logger.exception(f"捕获到异常: {exc}")

        if reraise:
            raise exc
