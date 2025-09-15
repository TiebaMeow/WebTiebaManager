from __future__ import annotations  # noqa: I001

import asyncio
from typing import Literal

from pydantic import BaseModel

from src.constance import BDUSS_MOSAIC, STOKEN_MOSAIC
from src.rule.rule import RuleInfo, Rules
from src.user.manager import User, UserManager

from ..server import (
    BaseResponse,
    app,
    current_user_depends,
    system_access_depends,
)

# 不要将下方的导入移动到TYPE_CHECKING中，否则会导致fastapi无法正确生处理请求

from src.rule.rule_set import RuleSetConfig  # noqa: TC001
from src.user.config import ForumConfig, ProcessConfig, UserPermission  # noqa: TC001
from src.user.confirm import ConfirmSimpleData  # noqa: TC001


class GetHomeInfoAccount(BaseModel):
    is_vip: bool
    portrait: str
    user_name: str
    nick_name: str


class GetHomeInfoData(BaseModel):
    enable: bool
    forum: str
    account: GetHomeInfoAccount | None
    permission: UserPermission


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
            permission=user.perm,
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
async def set_user_config(
    user: current_user_depends, system_access: system_access_depends, req: UserConfigData
) -> BaseResponse[bool]:
    config = user.config.model_copy(deep=True)
    if BDUSS_MOSAIC in req.forum.bduss:
        req.forum.bduss = user.config.forum.bduss
    if STOKEN_MOSAIC in req.forum.stoken:
        req.forum.stoken = user.config.forum.stoken
    config.forum = req.forum
    config.process = req.process
    try:
        await UserManager.update_config(config, system_access=system_access)
    except PermissionError as e:
        return BaseResponse(data=False, message=str(e), code=403)

    return BaseResponse(data=True)


@app.get("/api/rule/info", tags=["rule"])
async def get_rule_info(user: current_user_depends) -> BaseResponse[list[RuleInfo]]:
    return BaseResponse(data=list(Rules.rule_info.values()))


@app.get("/api/rule/get", tags=["rule"])
async def get_rule_sets(user: current_user_depends) -> BaseResponse[list[RuleSetConfig]]:
    return BaseResponse(data=user.config.rule_sets)


@app.post("/api/rule/set", tags=["rule"])
async def set_rule_sets(
    user: current_user_depends, system_access: system_access_depends, rule_sets: list[RuleSetConfig]
) -> BaseResponse[bool]:
    config = user.config.model_copy(deep=True)
    config.rule_sets = rule_sets
    try:
        await UserManager.update_config(config, system_access=system_access)
    except PermissionError as e:
        return BaseResponse(data=False, message=str(e), code=403)

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
