from fastapi import HTTPException
from pydantic import BaseModel, Field

from src.config import ServerConfig, SystemConfig
from src.control import Controller
from src.user.config import UserConfig, UserInfo
from src.user.manager import UserManager
from src.util.logging import system_logger

from .server import BaseResponse, Server, app


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


class GetInitializeInfoData(BaseModel):
    need_user: bool
    need_system: bool


@app.get("/api/initialize/get_info", tags=["initialize"])
async def get_initialize_info() -> BaseResponse[GetInitializeInfoData]:
    return BaseResponse(
        code=200, data=GetInitializeInfoData(need_system=Server.need_system(), need_user=await Server.need_user())
    )


@app.post("/api/initialize/initialize", tags=["initialize"])
async def initialize_post(request: InitializeRequest) -> BaseResponse[None]:
    if not await Server.need_initialize():
        raise HTTPException(status_code=400, detail="系统已经初始化")

    if await Server.need_user():
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
