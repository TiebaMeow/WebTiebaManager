from typing import Literal, TypedDict

from core.process.typedef import ProcessObject
from core.tieba.info import TiebaInfo

from .rule import Rules
from .template import LimiterRule, TextRule

user_register = Rules.fix_category("用户")


@user_register("用户名")
class UserNameRule(TextRule):
    type: Literal["UserName"] = "UserName"
    _target_attribute: str | list[str] = ["user", "user_name"]


@user_register("昵称")
class NickNameRule(TextRule):
    type: Literal["NickName"] = "NickName"
    _target_attribute: str | list[str] = ["user", "nick_name"]


@user_register("Portrait")
class PortraitRule(TextRule):
    type: Literal["Portrait"] = "Portrait"
    _target_attribute: str | list[str] = ["user", "portrait"]


@user_register("等级")
class LevelRule(LimiterRule):
    type: Literal["Level"] = "Level"
    _target_attribute: str | list[str] = ["user", "level"]


@user_register("IP")
class IpRule(TextRule):
    type: Literal["Ip"] = "Ip"
    priority: int = 45

    async def check(self, obj: ProcessObject) -> bool:
        # 调用api获取ip
        user_info = await TiebaInfo.get_user_info(obj)
        return await self._raw_check(user_info.ip)


@user_register("贴吧号")
class TiebaUidRUle(TextRule):
    type: Literal["TiebaUid"] = "TiebaUid"
    priority: int = 45

    async def check(self, obj: ProcessObject) -> bool:
        # 调用api获取ip
        user_info = await TiebaInfo.get_user_info(obj)
        return await self._raw_check(str(user_info.tieba_uid))
