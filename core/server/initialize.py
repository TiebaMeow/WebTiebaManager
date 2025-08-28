from fastapi import HTTPException
from pydantic import BaseModel, Field

from core.config import ServerConfig, SystemConfig
from core.control import Controller
from core.user.config import UserConfig, UserInfo
from core.user.manager import UserManager

from .server import Server, app


class UserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=32)


class SystemRequest(BaseModel):
    host: str = "0.0.0.0"
    port: int = 36800
    key: str
    token_expire_days: int = 7


class InitializeRequest(BaseModel):
    user: UserRequest | None = None
    system: SystemRequest | None = None


@app.get("/api/initialize/get_info", tags=["initialize"])
async def get_initialize_info():
    return {"code": 200, "data": {"need_user": await Server.need_user(), "need_system": await Server.need_system()}}


@app.post("/api/initialize/initialize", tags=["initialize"])
async def initialize_post(request: InitializeRequest):
    if not await Server.need_initialize():
        raise HTTPException(status_code=400, detail="系统已经初始化")

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

    Server.need_restart = True
    await Server.shutdown()
    return {"code": 200}
