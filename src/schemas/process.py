from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from tiebameow.models.dto import CommentDTO, PostDTO, ThreadDTO

    from .tieba import Content


class RuleContext(BaseModel):
    name: str
    whitelist: bool
    result: bool
    conditions: list[int]
    step_status: int | list[list[int]] | None = (
        None  # int: 失败步骤索引，list[list[int]]: [成功步骤, 失败步骤]，None: 全部成功 / 未经处理
    )


class ConditionContext(BaseModel):
    type: str
    context: str
    key: str | None = None


class ProcessObject[T]:
    content: Content
    dto: (
        ThreadDTO | PostDTO | CommentDTO | None
    )  # 处理对象对应的DTO数据，相比content具有更完整的字段信息，计划替换content
    data: T  # 处理过程中附加的数据

    def __init__(
        self, content: Content, data: T | None = None, dto: ThreadDTO | PostDTO | CommentDTO | None = None
    ) -> None:
        self.content = content
        self.data = data or {}  # type: ignore
        self.dto = dto

    def copy(self):
        return ProcessObject(content=self.content, dto=self.dto)


class ProcessOptions(BaseModel):
    need_confirm: bool = False
    execute_operations: bool = False
