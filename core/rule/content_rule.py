from typing import Literal

from core.process.typedef import ProcessObject
from .rule import Rules, RuleTemplate
from .template import TextRule, LimiterRule, CheckBoxRule


content_register = Rules.fix_category("帖子")


@content_register("帖子内容")
class ContentTextRule(TextRule):
    type: Literal["ContentText"] = "ContentText"
    _target_attribute: str | list[str] = "text"


@content_register("创建时间")
class CreateTimeRule(LimiterRule):
    type: Literal["CreateTime"] = "CreateTime"
    _target_attribute: str | list[str] = "create_time"


@content_register("楼层")
class FloorRule(LimiterRule):
    type: Literal["Floor"] = "Floor"
    _target_attribute: str | list[str] = "floor"


@content_register("类型", default_options={"value": []})
class ContentTypeRule(CheckBoxRule[Literal["Thread", "Post", "Comment"]]):
    type: Literal["ContentType"] = "ContentType"
    _target_attribute: str | list[str] = "type"
