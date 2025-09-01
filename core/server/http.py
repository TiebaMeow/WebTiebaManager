from pydantic import BaseModel

from core.constance import BDUSS_MOSAIC
from core.user.config import ForumConfig, ProcessConfig, UserConfig
from core.user.manager import UserManager

from .server import BaseResponse, app
from .token import current_user_depends


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
