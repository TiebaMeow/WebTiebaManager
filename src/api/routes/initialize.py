from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from src.core.config import ServerConfig, SystemConfig, UserConfig
from src.core.controller import Controller
from src.schemas.user import UserInfo
from src.user.manager import UserManager
from src.utils.logging import system_logger
from src.utils.tools import validate_password

from ..server import BaseResponse, Server, app


class UserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v):
        if not validate_password(v):
            raise ValueError("密码格式不正确")
        return v


class SystemRequest(BaseModel):
    host: str = "0.0.0.0"
    port: int = 36800
    key: str
    token_expire_days: int = 7

    @field_validator("key")
    @classmethod
    def validate_key(cls, v):
        if not validate_password(v):
            raise ValueError("密钥格式不正确")
        return v


class InitializeRequest(BaseModel):
    user: UserRequest | None = None
    system: SystemRequest | None = None
    secure_key: str


class GetInitializeInfoData(BaseModel):
    need_user: bool
    need_system: bool


@app.get("/api/initialize/get_info", tags=["initialize"])
async def get_initialize_info() -> BaseResponse[GetInitializeInfoData]:
    return BaseResponse(
        code=200, data=GetInitializeInfoData(need_system=Server.need_system(), need_user=Server.need_user())
    )


@app.post("/api/initialize/initialize", tags=["initialize"])
async def initialize_post(request: InitializeRequest) -> BaseResponse[None]:
    if not Server.need_initialize():
        raise HTTPException(status_code=400, detail="系统已经初始化")

    if request.secure_key != Server.secure_key():
        raise HTTPException(status_code=400, detail="初始化密钥错误")

    if Server.need_user():
        if not request.user:
            raise HTTPException(status_code=400, detail="请填写用户配置")
        user_config = UserConfig(user=UserInfo.model_validate(request.user.model_dump()))
        await UserManager.new_user(user_config, force=True)

    if Server.need_system():
        if not request.system:
            raise HTTPException(status_code=400, detail="请填写系统配置")

        system_config = SystemConfig(server=ServerConfig.model_validate(request.system.model_dump()))
        await Controller.update_config(system_config)

    system_logger.info("系统初始化完成，正在重启服务...")
    system_logger.info("如未能自动重启，请手动结束进程后重新运行")
    Server.need_restart = True
    await Server.shutdown()
    return BaseResponse(code=200, data=None)
