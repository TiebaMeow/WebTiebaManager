from typing import Literal

from src.schemas.process import ProcessObject

from .condition import Conditions
from .template import CheckBoxCondition, ContentCondition, LimiterCondition, TextCondition, TimeCondition

content_register = Conditions.fix_category("帖子")


@content_register("帖子内容")
class ContentTextCondition(TextCondition, ContentCondition):
    type: Literal["content_text"] = "content_text"
    _target_attribute: str | list[str] = "text"


@content_register("创建时间")
class CreateTimeCondition(TimeCondition, ContentCondition):
    type: Literal["create_time"] = "create_time"
    _target_attribute: str | list[str] = "create_time"


@content_register("楼层")
class FloorCondition(LimiterCondition, ContentCondition):
    type: Literal["floor"] = "floor"
    _target_attribute: str | list[str] = "floor"


CONTENT_TYPE_VALUES = {
    "thread": "主题帖",
    "post": "回帖",
    "comment": "楼中楼",
}


@content_register("类型", values=CONTENT_TYPE_VALUES)
class ContentTypeCondition(CheckBoxCondition[Literal["thread", "post", "comment"]], ContentCondition):
    type: Literal["content_type"] = "content_type"
    _target_attribute: str | list[str] = "type"

    async def resolve_context(self, obj: ProcessObject) -> str:
        value = await super().resolve_context(obj)
        return CONTENT_TYPE_VALUES.get(value, "未知类型")
