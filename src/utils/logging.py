from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, NamedTuple, Literal

import aiotieba
import colorama
from colorama import Fore, Style
from loguru import logger
from uvicorn.config import LOGGING_CONFIG

from src.core.constants import BASE_DIR, DEBUG, DEV

from .event import AsyncEvent

if TYPE_CHECKING:
    from loguru import Message, Record


colorama.just_fix_windows_console()


LEVEL_COLOR = {
    "INFO": Style.BRIGHT,
    "DEBUG": Fore.BLUE + Style.BRIGHT,
    "WARNING": Fore.YELLOW + Style.BRIGHT,
    "ERROR": Fore.RED + Style.BRIGHT,
    "CRITICAL": Fore.RED + Style.BRIGHT,
}


def supports_color() -> bool:
    """
    判断当前系统/终端环境是否支持 ANSI 颜色输出
    """
    # 1. 检查环境变量强制禁用
    if os.getenv("NO_COLOR") or os.getenv("TERM") == "dumb":
        return False

    # 2. 必须是 TTY (终端)
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False

    # 3. 非 Windows 系统通常支持
    if sys.platform != "win32":
        return True

    # 4. Windows 平台特殊检测
    # 检查是否运行在 Windows Terminal (WT_SESSION) 或有 ANSICON 支持 (如 Cmder)
    if "WT_SESSION" in os.environ or "ANSICON" in os.environ:
        return True

    # Windows 10 TH2 (10586) 之后原生支持 ANSI
    # Windows Server 2012 (NT 6.2) / 2012 R2 (NT 6.3) 原生不支持，会返回 False
    try:
        ver = sys.getwindowsversion()
        return ver.major >= 10
    except AttributeError:
        return False


LOGURU_DIAGNOSE = os.getenv("LOGURU_DIAGNOSE", "false").lower() == "true" or DEBUG


class ColorFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style: Literal["%", "{", "$"] = "%"):
        super().__init__(fmt, datefmt, style)
        self.use_color = supports_color()

    def formatTime(self, record, datefmt=None):  # noqa: N802
        s = super().formatTime(record, datefmt)
        return f"{Fore.GREEN}{s}{Style.RESET_ALL}" if self.use_color else s

    def format(self, record):
        # 如果不支持颜色，直接调用父类方法并跳过颜色逻辑
        if not self.use_color:
            return super().format(record)

        original_levelname = record.levelname
        log_level = record.levelname
        if log_level in LEVEL_COLOR:
            record.levelname = f"{LEVEL_COLOR[log_level]}{log_level}{Style.RESET_ALL}"

        result = super().format(record)

        # 恢复 record 的原始状态，避免影响其他处理器
        record.levelname = original_levelname
        return result


def get_uvicorn_log_config(name: str) -> dict:
    config = LOGGING_CONFIG.copy()
    config["formatters"] = {
        "default": {
            "()": "src.utils.logging.ColorFormatter",
            "fmt": f"{{asctime}} [{{levelname}}] {Fore.CYAN}{name}{Fore.RESET} | {{message}}",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "style": "{",
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": f"{Fore.GREEN}{{asctime}}{Fore.RESET} [{{levelname}}] {Fore.CYAN}{name}{Fore.RESET} "
            '| {client_addr} - "{request_line}" {status_code}',
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "style": "{",
            "use_colors": True,
        },
    }

    return config


def get_formatter(name: str) -> logging.Formatter:
    return ColorFormatter(
        f"{{asctime}} [{{levelname}}] {Fore.CYAN}{name}{Fore.RESET} | {{message}}", "%Y-%m-%d %H:%M:%S", style="{"
    )


aiotieba.logging.set_formatter(get_formatter("aiotieba.{funcName}"))


class LogEventData(NamedTuple):
    name: str | None
    message: Message


LogEvent = AsyncEvent[LogEventData]()


LOG_LEVEL = "DEBUG" if DEBUG else os.getenv("WTM_LOG_LEVEL", "INFO").upper()
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

    @classmethod
    def get_all_records(cls, limit: bool = True) -> list[Message]:
        messages: list[Message] = []
        for name in cls.messages:
            messages.extend(cls.messages[name])
        messages.sort(key=lambda msg: msg.record["time"].timestamp())
        if limit and len(messages) > cls.MAX_LINES:
            messages = messages[-cls.MAX_LINES :]
        return messages


# 移除默认处理器
logger.remove()

# 自定义格式
log_format_no_color = "{time:YYYY-MM-DD HH:mm:ss} [{level}] {extra[name]} | {message}"
log_format_color = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> [<level>{level}</level>] <cyan>{extra[name]}</cyan> | {message}"
)

logger.add(try_broadcast_log, format=log_format_no_color, level=LOG_LEVEL, diagnose=LOGURU_DIAGNOSE)

logger.add(LogRecorder.sink, format=log_format_no_color, level=LOG_LEVEL, diagnose=LOGURU_DIAGNOSE)


# 只在开发模式或调试模式下输出所有日志，否则只输出 system 日志和错误以上级别的日志
def console_filter(record: Record):
    if DEV or DEBUG:
        return True
    return record["extra"].get("name") == "system" or record["level"].no >= logger.level("ERROR").no


logger.add(
    sys.stdout,
    format=log_format_color,
    filter=console_filter,
    level=LOG_LEVEL,
    diagnose=LOGURU_DIAGNOSE,
    colorize=True,
)

# 修改文件处理器：输出到 logos 文件夹下
logger.add(
    LOG_DIR / "webtm_{time:YYYY-MM-DD}.log",
    format=log_format_no_color,
    rotation="00:00",
    retention="1 month",
    level=LOG_LEVEL,
    diagnose=LOGURU_DIAGNOSE,
)

logger.add(
    JSON_LOG_DIR / "webtm_{time:YYYY-MM-DD}.json",
    format=log_format_no_color,
    rotation="00:00",
    retention="1 month",
    level=LOG_LEVEL,
    serialize=True,
    diagnose=LOGURU_DIAGNOSE,
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
