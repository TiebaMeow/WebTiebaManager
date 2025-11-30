from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Literal

import aiofiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.constants import DEV
from src.core.controller import Controller
from src.utils.logging import JSON_LOG_DIR, LogEvent, LogEventData, LogRecorder, exception_logger, system_logger

from ..auth import current_user_depends, ensure_system_access_depends, parse_token
from ..server import BaseResponse, Server, app

if TYPE_CHECKING:
    from loguru import Message

# 不要将下方的导入移动到TYPE_CHECKING中，否则会导致fastapi无法正确生处理请求

from fastapi import Request  # noqa: TC002


class LogData(BaseModel):
    # TODO 移除name字段，改为从extra中获取
    message: str
    name: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "SUCCESS"]
    extra: dict
    time: str

    @staticmethod
    def from_message(message: Message) -> LogData:
        return LogData(
            message=message.record["message"],
            name=message.record["extra"].get("name", "unknown"),
            level=message.record["level"].name.upper(),  # type: ignore
            extra={k: v for k, v in message.record["extra"].items() if k != "name"},
            time=message.record["time"].strftime("%H:%M:%S"),
        )

    @staticmethod
    def from_json_message(message: dict, name: str = "unknown") -> LogData:
        return LogData(
            message=message["record"]["message"],
            name=message["record"]["extra"].get("name", name),
            level=message["record"]["level"]["name"].upper(),
            extra={k: v for k, v in message["record"]["extra"].items() if k != "name"},
            time=time.strftime("%H:%M:%S", time.localtime(message["record"]["time"]["timestamp"])),
        )


@app.get("/api/log/get_list", tags=["log"])
async def get_log_list(user: current_user_depends) -> BaseResponse[list[str]]:
    files = sorted(JSON_LOG_DIR.glob("webtm_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    return BaseResponse(data=[i.stem for i in files])


async def realtime_log(name: str, request: Request):
    records = [
        LogData.from_message(i)
        for i in (LogRecorder.get_all_records() if name == "system" else LogRecorder.get_records(name))
    ]
    queue = asyncio.Queue()

    for record in records:
        await queue.put(record)

    await queue.put(None)  # 用于标记初始日志发送完毕

    async def log_listener(data: LogEventData):
        try:
            if data.name != name and name != "system":
                # 不是发给当前用户的日志 / 订阅者不是 system
                return

            log_data = LogData.from_message(data.message)
            await queue.put(log_data)
        except Exception:
            system_logger.exception("推送实时日志失败")

    listener = LogEvent.on(log_listener)

    async def event_generator():
        try:
            while True:
                try:
                    log = await asyncio.wait_for(queue.get(), timeout=0.1)
                    if log is None:
                        yield "data: [DONE]\n\n"
                        continue

                    yield f"data: {json.dumps(log.model_dump(), ensure_ascii=False)}\n\n"
                except TimeoutError:
                    pass
                if await request.is_disconnected() or not Controller.running or Server.should_exit():
                    break
        except Exception:
            system_logger.exception("推送实时日志失败")
        finally:
            listener.un_register()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/log/realtime", tags=["log"])
async def user_realtime_log(request: Request, token: str) -> StreamingResponse:
    user, system_access = await parse_token(token)
    name = f"user.{user.username}"
    return await realtime_log(name, request)


@app.get("/api/system/log/realtime", tags=["system", "log"])
async def system_realtime_log(request: Request, token: str) -> StreamingResponse:
    user, system_access = await parse_token(token)
    if not system_access:
        return StreamingResponse(iter([]), media_type="text/event-stream")

    return await realtime_log("system", request)


async def get_log(target_name: str, file: str):
    path = JSON_LOG_DIR / f"{file}.json"
    if not path.exists() or not path.is_file():
        return BaseResponse(data=[], message="日志文件不存在", code=400)

    logs = []
    with exception_logger("读取日志文件失败", reraise=False):
        async with aiofiles.open(path, encoding="utf-8") as f:
            async for line in f:
                log = json.loads(line)
                name = log["record"]["extra"].get("name", "unknown")

                if name != target_name and target_name != "system":
                    # 不是当前用户的日志 / 订阅者不是 system
                    continue

                logs.append(LogData.from_json_message(log))

    return BaseResponse(data=logs)


@app.get("/api/log/get", tags=["log"])
async def get_user_log(user: current_user_depends, file: str) -> BaseResponse[list[LogData]]:
    user_name = f"user.{user.username}"
    return await get_log(user_name, file)


@app.get("/api/system/log/get", tags=["system", "log"])
async def get_system_log(system_access: ensure_system_access_depends, file: str) -> BaseResponse[list[LogData]]:
    return await get_log("system", file)
