from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from src.db.interface import Database
from src.process.typedef import ProcessObject
from src.util.anonymous import AnonymousAiotieba
from src.util.cache import ExpireCache
from src.util.logging import exception_logger

if TYPE_CHECKING:
    from aiotieba.typing import UserInfo


class TiebaInfo:
    user_info_cache: ExpireCache[UserInfo] = ExpireCache(expire_time=86400, mem_max_size=3250)

    class UserInfoDict(TypedDict):
        user_info: UserInfo | None

    @classmethod
    async def get_user_info(cls, data: str | int | ProcessObject[UserInfoDict]):
        with exception_logger("获取用户信息失败"):
            if isinstance(data, ProcessObject):
                if user_info := data.data.get("user_info"):
                    return user_info
                else:
                    _id = data.content.user.user_id
            else:
                _id = data

            if user_info := await cls.user_info_cache.get(_id):
                return user_info

            user_info = await (await AnonymousAiotieba.client()).get_user_info(_id)
            if user_info.user_id:
                await cls.user_info_cache.set(_id, user_info)

            if isinstance(data, ProcessObject):
                data.data["user_info"] = user_info

            return user_info

    class ThreadAuthorDict(TypedDict):
        is_thread_author: bool | None

    @classmethod
    async def get_if_thread_author(cls, data: ProcessObject[ThreadAuthorDict]):
        with exception_logger("获取是否为楼主失败"):
            if (is_thread_author := data.data.get("is_thread_author")) is not None:
                return is_thread_author

            if data.content.type == "thread":
                data.data["is_thread_author"] = True
            else:
                thread = await Database.get_thread_by_tid(data.content.tid)
                if thread:
                    data.data["is_thread_author"] = thread.author_id == data.content.user.user_id
                else:
                    posts = await (await AnonymousAiotieba.client()).get_posts(
                        data.content.tid
                    )  # try to fetch thread info
                    if posts:
                        data.data["is_thread_author"] = posts.thread.user.user_id == data.content.user.user_id
                    else:
                        data.data["is_thread_author"] = False

            return data.data["is_thread_author"]
