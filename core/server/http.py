import asyncio
import io
from typing import Literal

import aiotieba
import cv2
import numpy as np
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.constance import BDUSS_MOSAIC
from core.control import Controller
from core.rule.rule import RuleInfo, Rules
from core.rule.rule_set import RuleSetConfig
from core.user.config import ForumConfig, ProcessConfig
from core.user.confirm import ConfirmSimpleData
from core.user.manager import User, UserManager

from .server import BaseResponse, app
from .token import current_user_depends


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
    return BaseResponse(data=await UserManager.disbale_user(user.username))


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
    if BDUSS_MOSAIC in req.forum.stoken:
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
        data=[i.simple for i in sorted(user.confirm.data.values(), key=lambda x: x.process_time, reverse=True)]
    )


class ConfirmRequest(BaseModel):
    pid: int | list[int]
    action: Literal["ignore", "execute"]


async def confirm_many(user: User, pids: list[int], action: Literal["ignore", "execute"]):
    confirms = [confirm for pid in pids if (confirm := user.confirm.get(pid))]
    for confirm in confirms:
        await user.operate_confirm(confirm, action)


@app.post("/api/confirm/confirm", tags=["confirm"])
async def confirm_operation(user: current_user_depends, request: ConfirmRequest) -> BaseResponse[bool]:
    if request.action == "execute" and not user.client.info:
        return BaseResponse(data=False, message="账号未登录，不能执行确认操作", code=400)

    if isinstance(request.pid, int):
        if not (confirm := user.confirm.get(request.pid)):
            return BaseResponse(data=False, message="内容不存在", code=400)

        await user.operate_confirm(confirm, request.action)
        return BaseResponse(data=True, message="操作成功")
    else:
        asyncio.create_task(confirm_many(user, request.pid, request.action))
        return BaseResponse(data=True, message="正在批量执行操作，请稍后查看结果")


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
