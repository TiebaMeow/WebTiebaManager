from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from src.tieba.info import TiebaInfo

from .condition import Conditions
from .template import LimiterCondition, TextCondition

if TYPE_CHECKING:
    from src.schemas.process import ProcessObject

user_register = Conditions.fix_category("用户")


@user_register("用户名")
class UserNameCondition(TextCondition):
    type: Literal["user_name"] = "user_name"
    _target_attribute: str | list[str] = ["user", "user_name"]


@user_register("昵称")
class NickNameCondition(TextCondition):
    type: Literal["nick_name"] = "nick_name"
    _target_attribute: str | list[str] = ["user", "nick_name"]


@user_register("Portrait")
class PortraitCondition(TextCondition):
    type: Literal["portrait"] = "portrait"
    _target_attribute: str | list[str] = ["user", "portrait"]


@user_register("等级")
class LevelCondition(LimiterCondition):
    type: Literal["level"] = "level"
    _target_attribute: str | list[str] = ["user", "level"]


@user_register("IP")
class IpCondition(TextCondition):
    type: Literal["ip"] = "ip"
    priority: int = 45

    async def check(self, obj: ProcessObject) -> bool:
        # 调用api获取ip
        user_info = await TiebaInfo.get_user_info(obj)
        return await self._raw_check(user_info.ip)


@user_register("贴吧号")
class TiebaUidCondition(TextCondition):
    type: Literal["tieba_uid"] = "tieba_uid"
    priority: int = 45

    async def check(self, obj: ProcessObject) -> bool:
        # 调用api获取贴吧号
        user_info = await TiebaInfo.get_user_info(obj)
        return await self._raw_check(str(user_info.tieba_uid))
