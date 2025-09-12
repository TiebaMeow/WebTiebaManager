from __future__ import annotations

import asyncio
import io
import json
from typing import TYPE_CHECKING, Literal

import aiotieba
import cv2
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.constance import BDUSS_MOSAIC, STOKEN_MOSAIC
from src.control import Controller
from src.rule.rule import RuleInfo, Rules
from src.user.manager import User, UserManager
from src.util.cache import ClearCache
from src.util.logging import JSON_LOG_DIR, LogEvent, LogEventData, LogRecorder, system_logger

from .server import BaseResponse, app
from .token import current_user_depends, parse_token, system_access_depends

if TYPE_CHECKING:
    import numpy as np
    from loguru import Message

# 不要将下方的导入移动到TYPE_CHECKING中，否则会导致fastapi无法正确生处理请求

from fastapi import Request  # noqa: TC002

from src.rule.rule_set import RuleSetConfig  # noqa: TC001
from src.user.config import ForumConfig, ProcessConfig  # noqa: TC001
from src.user.confirm import ConfirmSimpleData  # noqa: TC001


class AnonymousClient:
    client: aiotieba.Client | None = None

    @classmethod
    async def start(cls):
        cls.client = aiotieba.Client()
        await cls.client.__aenter__()
        return cls.client

    @classmethod
    async def get_client(cls):
        if not cls.client:
            return await cls.start()
        return cls.client

    @classmethod
    async def stop(cls, _=None):
        if cls.client:
            await cls.client.__aexit__()
            cls.client = None


Controller.Stop.on(AnonymousClient.stop)


class GetHomeInfoAccount(BaseModel):
    is_vip: bool
    portrait: str
    user_name: str
    nick_name: str


class GetHomeInfoData(BaseModel):
    enable: bool
    forum: str
    account: GetHomeInfoAccount | None


@app.get("/api/user/info", tags=["user"])
async def get_home_info(user: current_user_depends) -> BaseResponse[GetHomeInfoData]:
    return BaseResponse(
        data=GetHomeInfoData(
            enable=user.enable,
            forum=user.fname,
            account=GetHomeInfoAccount(
                user_name=user.client.info.user_name,
                nick_name=user.client.info.nick_name,
                portrait=user.client.info.portrait,
                is_vip=user.client.info.is_vip,
            )
            if user.client.info
            else None,
        ),
    )


@app.post("/api/user/enable", tags=["user"])
async def enable_user(user: current_user_depends) -> BaseResponse[bool]:
    return BaseResponse(data=await UserManager.enable_user(user.username))


@app.post("/api/user/disable", tags=["user"])
async def disable_user(user: current_user_depends) -> BaseResponse[bool]:
    return BaseResponse(data=await UserManager.disable_user(user.username))


class UserConfigData(BaseModel):
    forum: ForumConfig
    process: ProcessConfig


@app.get("/api/config/get_user", tags=["config"])
async def get_user_config(user: current_user_depends) -> BaseResponse[UserConfigData]:
    return BaseResponse(data=UserConfigData(forum=user.config.forum.mosaic, process=user.config.process))


@app.post("/api/config/set_user", tags=["config"])
async def set_user_config(user: current_user_depends, req: UserConfigData) -> BaseResponse[bool]:
    config = user.config.model_copy(deep=True)
    if BDUSS_MOSAIC in req.forum.bduss:
        req.forum.bduss = user.config.forum.bduss
    if STOKEN_MOSAIC in req.forum.stoken:
        req.forum.stoken = user.config.forum.stoken
    config.forum = req.forum
    config.process = req.process
    await UserManager.update_config(config)

    return BaseResponse(data=True)


@app.get("/api/rule/info", tags=["rule"])
async def get_rule_info(user: current_user_depends) -> BaseResponse[list[RuleInfo]]:
    return BaseResponse(data=list(Rules.rule_info.values()))


@app.get("/api/rule/get", tags=["rule"])
async def get_rule_sets(user: current_user_depends) -> BaseResponse[list[RuleSetConfig]]:
    return BaseResponse(data=user.config.rule_sets)


@app.post("/api/rule/set", tags=["rule"])
async def set_rule_sets(user: current_user_depends, rule_sets: list[RuleSetConfig]) -> BaseResponse[bool]:
    config = user.config.model_copy(deep=True)
    config.rule_sets = rule_sets
    await UserManager.update_config(config)
    return BaseResponse(data=True)


@app.get("/api/confirm/get_list", tags=["confirm"])
async def get_confirm_list(user: current_user_depends) -> BaseResponse[list[ConfirmSimpleData]]:
    return BaseResponse(
        data=[i.simple for i in sorted(await user.confirm.values(), key=lambda x: x.content.create_time, reverse=True)]
    )


class ConfirmRequest(BaseModel):
    pid: int | list[int]
    action: Literal["ignore", "execute"]


async def confirm_many(user: User, pids: list[int], action: Literal["ignore", "execute"]):
    confirms = [confirm for pid in pids if (confirm := await user.confirm.get(pid))]
    for confirm in confirms:
        await user.operate_confirm(confirm, action)


@app.post("/api/confirm/confirm", tags=["confirm"])
async def confirm_operation(user: current_user_depends, request: ConfirmRequest) -> BaseResponse[bool]:
    if request.action == "execute" and not user.client.info:
        return BaseResponse(data=False, message="账号未登录，不能执行确认操作", code=400)

    if isinstance(request.pid, int):
        if not (confirm := await user.confirm.get(request.pid)):
            return BaseResponse(data=False, message="内容不存在", code=400)

        await user.operate_confirm(confirm, request.action)
        return BaseResponse(data=True, message="操作成功")
    else:
        asyncio.create_task(confirm_many(user, request.pid, request.action))
        return BaseResponse(data=True, message="正在批量执行操作，请稍后查看结果")


@app.post("/api/cache/clear", tags=["cache"], description="手动清理缓存")
async def clear_confirms(system_access: system_access_depends) -> BaseResponse[bool]:
    await ClearCache.broadcast(None)
    return BaseResponse(data=True, message="操作成功")


class LogData(BaseModel):
    message: str
    name: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    extra: dict

    @staticmethod
    def from_message(message: Message) -> LogData:
        return LogData(
            message=message.rstrip("\n"),
            name=message.record["extra"].get("name", "unknown"),
            level=message.record["level"].name.upper(),  # type: ignore
            extra={k: v for k, v in message.record["extra"].items() if k != "name"},
        )


@app.get("/api/log/get_list", tags=["log"])
async def get_log_list(user: current_user_depends) -> BaseResponse[list[str]]:
    files = sorted(JSON_LOG_DIR.glob("webtm_*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    return BaseResponse(data=[i.stem for i in files])


@app.get("/api/log/user_realtime", tags=["log"])
async def user_realtime_log(request: Request, token: str) -> StreamingResponse:
    user, system_access = await parse_token(token)
    name = f"user.{user.username}"

    records = [LogData.from_message(i) for i in LogRecorder.get_records(name)]
    queue = asyncio.Queue()

    for record in records:
        await queue.put(record)

    async def log_listener(data: LogEventData):
        try:
            if data.name != name:
                return

            log_data = LogData.from_message(data.message)
            await queue.put(log_data)
        except Exception:
            system_logger.exception("推送日志时发生错误")

    listener = LogEvent.on(log_listener)

    async def event_generator():
        try:
            while True:
                log = await queue.get()
                yield f"data: {json.dumps(log.model_dump(), ensure_ascii=False)}\n\n"
                if await request.is_disconnected():
                    break
        except Exception:
            system_logger.exception("推送日志时发生错误")
        finally:
            listener.un_register()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/log/get_user", tags=["log"])
async def get_user_log(user: current_user_depends, file: str) -> BaseResponse[list[LogData]]:
    path = JSON_LOG_DIR / f"{file}.json"
    if not path.exists() or not path.is_file():
        return BaseResponse(data=[], message="日志文件不存在", code=400)

    logs = []
    user_name = f"user.{user.username}"
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                log = json.loads(line)
                extra = log["record"]["extra"]
                if "name" in extra:
                    name = extra["name"]
                    del extra["name"]
                else:
                    name = "unknown"

                if name != user_name:
                    continue

                logs.append(
                    LogData(
                        message=log["text"].rstrip("\n"),
                        name=name,
                        level=log["record"]["level"]["name"].upper(),
                        extra=extra,
                    )
                )
            except Exception:
                continue

    return BaseResponse(data=logs)


def ndarray2image(image: np.ndarray | None) -> io.BytesIO:
    if image is None or not image.any():
        image_bytes = b""
    else:
        image_bytes = cv2.imencode(".webp", image)[1].tobytes()

    return io.BytesIO(image_bytes)


@app.get("/resources/portrait/{portrait}", tags=["resources"])
async def get_portrait(portrait: str) -> StreamingResponse:
    image = await (await AnonymousClient.get_client()).get_portrait(portrait, size="s")
    return StreamingResponse(
        content=ndarray2image(image.img),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/resources/image/{hash}", tags=["resources"])
async def get_image(hash: str, size: Literal["s", "m", "l"] = "s") -> StreamingResponse:  # noqa: A002
    image = await (await AnonymousClient.get_client()).hash2image(hash, size=size)
    return StreamingResponse(
        content=ndarray2image(image.img),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )
