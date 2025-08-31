from pydantic import BaseModel

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
            enable=user.config.enable,
            forum=user.config.forum.fname,
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
