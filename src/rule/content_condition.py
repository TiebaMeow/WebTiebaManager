from typing import Literal

from .condition import Conditions
from .template import CheckBoxCondition, LimiterCondition, TextCondition, TimeCondition

content_register = Conditions.fix_category("帖子")


@content_register("帖子内容")
class ContentTextCondition(TextCondition):
    type: Literal["content_text"] = "content_text"
    _target_attribute: str | list[str] = "text"


@content_register("创建时间")
class CreateTimeCondition(TimeCondition):
    type: Literal["create_time"] = "create_time"
    _target_attribute: str | list[str] = "create_time"


@content_register("楼层")
class FloorCondition(LimiterCondition):
    type: Literal["floor"] = "floor"
    _target_attribute: str | list[str] = "floor"


# 需要更新支持
@content_register("类型", values={"thread": "主题帖", "post": "回帖", "comment": "楼中楼"})
class ContentTypeCondition(CheckBoxCondition[Literal["thread", "post", "comment"]]):
    type: Literal["content_type"] = "content_type"
    _target_attribute: str | list[str] = "type"
