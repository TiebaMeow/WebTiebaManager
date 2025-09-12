from typing import Literal, TypedDict

from src.process.typedef import ProcessObject
from src.tieba.info import TiebaInfo

from .rule import Rules
from .template import LimiterRule, TextRule

user_register = Rules.fix_category("用户")


@user_register("用户名")
class UserNameRule(TextRule):
    type: Literal["user_name"] = "user_name"
    _target_attribute: str | list[str] = ["user", "user_name"]


@user_register("昵称")
class NickNameRule(TextRule):
    type: Literal["nick_name"] = "nick_name"
    _target_attribute: str | list[str] = ["user", "nick_name"]


@user_register("Portrait")
class PortraitRule(TextRule):
    type: Literal["portrait"] = "portrait"
    _target_attribute: str | list[str] = ["user", "portrait"]


@user_register("等级")
class LevelRule(LimiterRule):
    type: Literal["level"] = "level"
    _target_attribute: str | list[str] = ["user", "level"]


@user_register("IP")
class IpRule(TextRule):
    type: Literal["ip"] = "ip"
    priority: int = 45

    async def check(self, obj: ProcessObject) -> bool:
        # 调用api获取ip
        user_info = await TiebaInfo.get_user_info(obj)
        return await self._raw_check(user_info.ip)


@user_register("贴吧号")
class TiebaUidRUle(TextRule):
    type: Literal["tieba_uid"] = "tieba_uid"
    priority: int = 45

    async def check(self, obj: ProcessObject) -> bool:
        # 调用api获取ip
        user_info = await TiebaInfo.get_user_info(obj)
        return await self._raw_check(str(user_info.tieba_uid))
