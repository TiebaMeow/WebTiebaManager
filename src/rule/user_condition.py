from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from src.schemas.process import ProcessObject
from src.tieba.info import TiebaInfo

from .condition import Conditions
from .template import ContentCondition, LimiterCondition, TextCondition

if TYPE_CHECKING:
    from src.schemas.process import ProcessObject

user_register = Conditions.fix_category("用户")


@user_register("用户名")
class UserNameCondition(TextCondition, ContentCondition):
    type: Literal["user_name"] = "user_name"
    _target_attribute: str | list[str] = ["user", "user_name"]


@user_register("昵称")
class NickNameCondition(TextCondition, ContentCondition):
    type: Literal["nick_name"] = "nick_name"
    _target_attribute: str | list[str] = ["user", "nick_name"]


@user_register("Portrait")
class PortraitCondition(TextCondition, ContentCondition):
    type: Literal["portrait"] = "portrait"
    _target_attribute: str | list[str] = ["user", "portrait"]


@user_register("等级")
class LevelCondition(LimiterCondition, ContentCondition):
    type: Literal["level"] = "level"
    _target_attribute: str | list[str] = ["user", "level"]


@user_register("IP")
class IpCondition(TextCondition):
    type: Literal["ip"] = "ip"
    priority: int = 45

    async def get_value(self, obj: ProcessObject) -> str:
        user_info = await TiebaInfo.get_user_info(obj)
        return user_info.ip


@user_register("贴吧号")
class TiebaUidCondition(TextCondition):
    type: Literal["tieba_uid"] = "tieba_uid"
    priority: int = 45

    async def get_value(self, obj: ProcessObject) -> str:
        user_info = await TiebaInfo.get_user_info(obj)
        return str(user_info.tieba_uid)
