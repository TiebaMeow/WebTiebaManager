from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel

from src.core.config import ForumConfig, ProcessConfig, RuleConfig  # noqa: TC001
from src.rule.condition import Conditions
from src.schemas.rule import ConditionInfo  # noqa: TC001

# 不要将下方的导入移动到TYPE_CHECKING中，否则会导致fastapi无法正确生处理请求
from src.schemas.user import ConfirmSimpleData, UserPermission  # noqa: TC001
from src.user.manager import User, UserManager
from src.user.user import TiebaClientStatus

from ..auth import current_user_depends, system_access_depends  # noqa: TC001
from ..server import BaseResponse, app


class GetHomeInfoAccount(BaseModel):
    is_vip: bool = False
    portrait: str = ""
    user_name: str = ""
    nick_name: str = ""
    status: TiebaClientStatus
    failed_reason: str = ""


class GetHomeInfoData(BaseModel):
    enable: bool
    forum: str
    account: GetHomeInfoAccount | None
    permission: UserPermission


@app.get("/api/user/info", tags=["user"])
async def get_home_info(user: current_user_depends) -> BaseResponse[GetHomeInfoData]:
    if user.client.status == TiebaClientStatus.MISSING_COOKIE:
        account = GetHomeInfoAccount(status=TiebaClientStatus.MISSING_COOKIE)
    elif user.client.status == TiebaClientStatus.FAILED:
        account = GetHomeInfoAccount(
            status=TiebaClientStatus.FAILED, failed_reason=user.client.failed_reason or "未知错误"
        )
    elif user.client.status == TiebaClientStatus.SUCCESS and user.client.info:
        account = GetHomeInfoAccount(
            status=TiebaClientStatus.SUCCESS,
            user_name=user.client.info.user_name,
            nick_name=user.client.info.nick_name,
            portrait=user.client.info.portrait,
            is_vip=user.client.info.is_vip,
        )
    else:
        account = None

    return BaseResponse(
        data=GetHomeInfoData(
            enable=user.enable,
            forum=user.fname,
            account=account,
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

    mosaic_forum = user.config.forum.mosaic
    if req.forum.bduss == mosaic_forum.bduss:
        req.forum.bduss = user.config.forum.bduss
    if req.forum.stoken == mosaic_forum.stoken:
        req.forum.stoken = user.config.forum.stoken

    config.forum = req.forum
    config.process = req.process
    try:
        await UserManager.update_config(config, system_access=system_access)
    except PermissionError as e:
        return BaseResponse(data=False, message=str(e), code=403)

    return BaseResponse(data=True)


@app.get("/api/rule/info", tags=["rule"])
async def get_condition_info(user: current_user_depends) -> BaseResponse[list[ConditionInfo]]:
    return BaseResponse(data=list(Conditions.condition_info.values()))


@app.get("/api/rule/get", tags=["rule"])
async def get_rules(user: current_user_depends) -> BaseResponse[list[RuleConfig]]:
    return BaseResponse(data=user.config.rules)


@app.post("/api/rule/set", tags=["rule"])
async def set_rules(
    user: current_user_depends, system_access: system_access_depends, rules: list[RuleConfig]
) -> BaseResponse[bool]:
    config = user.config.model_copy(deep=True)
    config.rules = rules
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
    if isinstance(request.pid, int):
        if not (confirm := await user.confirm.get(request.pid)):
            return BaseResponse(data=False, message="内容不存在", code=400)
        try:
            await user.operate_confirm(confirm, request.action)
        except ValueError:
            return BaseResponse(data=False, message="账号未登录，无法执行需要吧务权限的操作", code=400)

        return BaseResponse(data=True, message="操作成功")
    else:
        asyncio.create_task(confirm_many(user, request.pid, request.action))
        return BaseResponse(data=True, message="正在批量执行操作，请稍后查看结果")
