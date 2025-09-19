from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from src.config import SystemConfig  # noqa: TC001
from src.constance import BASE_DIR, CODE_EXPIRE
from src.control import Controller
from src.db.config import DatabaseConfig  # noqa: TC001
from src.db.interface import Database
from src.server import BaseResponse, app, ensure_system_access_depends, ip_depends
from src.user.config import (
    ForumConfig,
    UserConfig,
    UserInfo,
    UserPermission,  # noqa: TC001
)
from src.user.manager import UserManager
from src.util.cache import ClearCache, ExpireCache
from src.util.logging import system_logger
from src.util.tools import random_str, validate_password


@app.post("/api/system/clear_cache", tags=["clear_cache"], description="手动清理缓存")
async def clear_confirms(system_access: ensure_system_access_depends) -> BaseResponse[bool]:
    await ClearCache.broadcast(None)
    return BaseResponse(data=True, message="操作成功")


class UserInfodata(BaseModel):
    username: str = Field(min_length=0, max_length=32, default="")
    permission: UserPermission
    forum: str
    code: str = Field(..., min_length=0, max_length=32)
    use: bool = False


CodeCache = ExpireCache[UserInfodata](expire_time=CODE_EXPIRE, directory=BASE_DIR / "code")


@app.get("/api/system/get_users_info", tags=["system"])
async def get_users_info(system_access: ensure_system_access_depends) -> BaseResponse[list[UserInfodata]]:
    data = [
        UserInfodata(
            username=user.username, permission=user.perm, forum=user.fname, code=user.config.user.code, use=True
        )
        for user in UserManager.users.values()
    ]
    existed_code = {u.config.user.code for u in UserManager.users.values()}
    data.extend(info for key, info in await CodeCache.items() if key not in existed_code)
    return BaseResponse(data=data)


@app.post("/api/system/set_user_info", tags=["system"])
async def set_user_info(system_access: ensure_system_access_depends, req: UserInfodata) -> BaseResponse[bool]:
    if req.username and (user := UserManager.get_user(req.username)):
        config = user.config.model_copy(deep=True)
        config.permission = req.permission
        config.forum.fname = req.forum
        await UserManager.update_config(config, system_access=system_access)
    elif req.code and (data := await CodeCache.get(req.code)):
        data.username = req.username
        data.permission = req.permission
        data.forum = req.forum
        await CodeCache.set(req.code, data)
        system_logger.info(f"更新邀请码 {req.code} 信息")
    else:
        return BaseResponse(data=False, message="用户不存在或邀请码无效", code=400)

    return BaseResponse(data=True, message="操作成功")


class DeleteRequest(BaseModel):
    username: str = Field(..., min_length=0, max_length=32)
    code: str = Field(..., min_length=0, max_length=32)


@app.post("/api/system/delete_user", tags=["system"])
async def delete_user(system_access: ensure_system_access_depends, req: DeleteRequest) -> BaseResponse[bool]:
    if req.username and UserManager.get_user(req.username):
        if len(UserManager.users.keys()) <= 1:
            return BaseResponse(code=400, data=False, message="不能删除最后一个用户")

        try:
            await UserManager.delete_user(req.username)
        except Exception as e:
            return BaseResponse(data=False, message=str(e))
    elif req.code and await CodeCache.get(req.code):
        await CodeCache.delete(req.code)

        system_logger.info(f"删除邀请码 {req.code}")
    else:
        return BaseResponse(code=400, data=False, message="用户不存在或邀请码无效")

    return BaseResponse(data=True, message="操作成功")


@app.post("/api/system/create_invite_code", tags=["system"])
async def create_invite_code(system_access: ensure_system_access_depends, req: UserInfodata) -> BaseResponse[str]:
    if not req.code:
        for _ in range(10):
            req.code = random_str(8)
            if CodeCache.get(req.code) is None:
                break
        else:
            raise HTTPException(status_code=500, detail="邀请码生成失败，请稍后重试")

    if req.username:
        return BaseResponse(code=400, data="", message="创建邀请码时用户名必须为空")

    while any(u.config.user.code == req.code for u in UserManager.users.values()):
        return BaseResponse(code=400, data="", message="邀请码已存在，请更换后重试")
    if await CodeCache.get(req.code):
        return BaseResponse(code=400, data="", message="邀请码已存在，请更换后重试")

    await CodeCache.set(req.code, req)

    system_logger.info(f"创建邀请码 {req.code}")
    return BaseResponse(data=req.code, message="操作成功，邀请码七天内有效，请尽快使用")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str
    code: str = Field(..., min_length=1, max_length=32)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if not validate_password(v):
            raise ValueError("密码格式不正确")
        return v


@app.post("/api/register", tags=["register"])
async def register_user(req: RegisterRequest, ip: ip_depends) -> BaseResponse[bool]:
    if UserManager.get_user(req.username):
        return BaseResponse(code=400, data=False, message="用户名已存在")

    if not (data := await CodeCache.get(req.code)):
        return BaseResponse(code=400, data=False, message="邀请码无效")

    config = UserConfig(
        user=UserInfo(
            username=req.username,
            password=req.password,
            code=req.code,
        ),
        permission=data.permission,
        forum=ForumConfig(fname=data.forum),
    )
    try:
        await UserManager.new_user(config)
    except Exception as e:
        return BaseResponse(data=False, message=str(e))

    await CodeCache.delete(req.code)

    system_logger.info(f"用户 {req.username} 注册成功 IP: {ip}")
    return BaseResponse(data=True, message="注册成功，请使用用户名和密码登录")


@app.get("/api/system/get_config", tags=["system"])
async def get_config(system_access: ensure_system_access_depends) -> BaseResponse[SystemConfig]:
    return BaseResponse(data=Controller.config.mosaic)


@app.post("/api/system/set_config", tags=["system"])
async def set_config(system_access: ensure_system_access_depends, req: SystemConfig) -> BaseResponse[bool]:
    try:
        new_config = Controller.config.apply_new(req)
        server_update = new_config.server != Controller.config.server
        await Controller.update_config(new_config)
    except PermissionError as e:
        return BaseResponse(data=False, message=str(e), code=403)
    except ValueError as e:
        return BaseResponse(data=False, message=str(e), code=400)
    except Exception as e:
        return BaseResponse(data=False, message=str(e), code=500)

    if server_update:
        system_logger.info("检测到服务器配置变更，请重启程序以应用更改")
        return BaseResponse(data=True, message="保存成功，请重启程序以应用更改")
    else:
        return BaseResponse(data=True, message="保存成功")


@app.post("/api/system/test_db_connection", tags=["system"], description="测试数据库连接")
async def test_db(req: DatabaseConfig, system_access: ensure_system_access_depends) -> BaseResponse[bool]:
    config = Controller.config.database.apply_new(req)
    success, err = await Database.test_connection(config)
    if err:
        return BaseResponse(data=False, message=f"数据库连接失败 {err}", code=400)

    return BaseResponse(data=True, message="数据库连接成功")
