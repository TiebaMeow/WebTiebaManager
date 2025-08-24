from typing import TypedDict

import aiotieba

from core.control import Controller
from core.process.typedef import ProcessObject
from core.util.cache import ExpireCache


class UserInfoDict(TypedDict):
    user_info: aiotieba.typing.UserInfo | None


class TiebaInfo:
    client: aiotieba.Client | None = None
    user_info_cache = ExpireCache[aiotieba.typing.UserInfo]()

    @classmethod
    async def stop(cls):
        if cls.client:
            await cls.client.__aexit__()
            cls.client = None

    @classmethod
    async def get_client(cls) -> aiotieba.Client:
        if not cls.client:
            cls.client = aiotieba.Client()
            await cls.client.__aenter__()

        return cls.client

    @classmethod
    async def get_user_info(cls, data: str | int | ProcessObject[UserInfoDict]):
        if isinstance(data, ProcessObject):
            if user_info := data.data.get("user_info"):
                return user_info
            else:
                _id = data.content.user.user_id
        else:
            _id = data

        if user_info := cls.user_info_cache.get(_id):
            return user_info

        user_info = await (await cls.get_client()).get_user_info(_id)
        if user_info.user_id:
            cls.user_info_cache.set(_id, user_info)

        if isinstance(data, ProcessObject):
            data.data["user_info"] = user_info

        return user_info
