from typing import Literal

from .rule import Rules
from .template import CheckBoxRule, LimiterRule, TextRule, TimeRule

content_register = Rules.fix_category("帖子")


@content_register("帖子内容")
class ContentTextRule(TextRule):
    type: Literal["content_text"] = "content_text"
    _target_attribute: str | list[str] = "text"


@content_register("创建时间")
class CreateTimeRule(TimeRule):
    type: Literal["create_time"] = "create_time"
    _target_attribute: str | list[str] = "create_time"


@content_register("楼层")
class FloorRule(LimiterRule):
    type: Literal["floor"] = "floor"
    _target_attribute: str | list[str] = "floor"


# 需要更新支持
@content_register("类型", values={"thread": "主题帖", "post": "回帖", "comment": "楼中楼"})
class ContentTypeRule(CheckBoxRule[Literal["thread", "post", "comment"]]):
    type: Literal["content_type"] = "content_type"
    _target_attribute: str | list[str] = "type"
