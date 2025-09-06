from typing import Literal

from .rule import Rules
from .template import CheckBoxRule, LimiterRule, TextRule, TimeRule

content_register = Rules.fix_category("帖子")


@content_register("帖子内容")
class ContentTextRule(TextRule):
    type: Literal["ContentText"] = "ContentText"
    _target_attribute: str | list[str] = "text"


@content_register("创建时间")
class CreateTimeRule(TimeRule):
    type: Literal["CreateTime"] = "CreateTime"
    _target_attribute: str | list[str] = "create_time"


@content_register("楼层")
class FloorRule(LimiterRule):
    type: Literal["Floor"] = "Floor"
    _target_attribute: str | list[str] = "floor"


# 需要更新支持
@content_register("类型", values={"Thread": "主题帖", "Post": "回帖", "Comment": "楼中楼"})
class ContentTypeRule(CheckBoxRule[Literal["Thread", "Post", "Comment"]]):
    type: Literal["ContentType"] = "ContentType"
    _target_attribute: str | list[str] = "type"
