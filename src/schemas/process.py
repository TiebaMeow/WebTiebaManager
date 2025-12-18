from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
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
    data: T  # 处理过程中附加的数据

    def __init__(self, content: Content, data: T | None = None) -> None:
        self.content = content
        self.data = data or {}  # type: ignore


class ProcessOptions(BaseModel):
    need_confirm: bool = False
    execute_operations: bool = False
