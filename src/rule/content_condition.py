from typing import Literal

import yarl

from src.schemas.process import ProcessObject

from .condition import Conditions
from .template import (
    CheckBoxCondition,
    ContentCondition,
    LimiterCondition,
    TextCondition,
    TimeCondition,
)

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


@content_register("标题")
class TitleCondition(TextCondition, ContentCondition):
    type: Literal["title"] = "title"
    _target_attribute: str | list[str] = "title"


@content_register("链接")
class LinkCondition(TextCondition):
    type: Literal["link"] = "link"

    @staticmethod
    def get_real_url(url: str) -> str:
        try:
            parsed_url = yarl.URL(url)
            if parsed_url.path == "/mo/q/checkurl":
                return parsed_url.query.get("url", url)

            return url
        except Exception:
            return url

    async def resolve_context(self, obj: ProcessObject, processed: bool = False) -> str:
        if not obj.dto:
            return "链接规则暂不支持重处理"

        return "\n".join(await self.get_value(obj))

    async def get_value(self, obj: ProcessObject) -> list[str]:
        links = []

        if obj.dto is not None:
            links.extend(self.get_real_url(content.raw_url) for content in obj.dto.contents if content.type == "link")

        return links

    async def check(self, obj: ProcessObject) -> bool:
        for link in await self.get_value(obj):
            if self.text_check(link):
                return True

        return False


CONTENT_TYPE_VALUES = {
    "thread": "主题帖",
    "post": "回帖",
    "comment": "楼中楼",
}


@content_register("类型", values=CONTENT_TYPE_VALUES)
class ContentTypeCondition(CheckBoxCondition[Literal["thread", "post", "comment"]], ContentCondition):
    type: Literal["content_type"] = "content_type"
    _target_attribute: str | list[str] = "type"

    async def resolve_context(self, obj: ProcessObject, processed: bool = False) -> str:
        value = await super().resolve_context(obj, processed=processed)
        return CONTENT_TYPE_VALUES.get(value, "未知类型")
