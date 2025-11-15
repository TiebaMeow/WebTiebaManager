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
    failed_step: int | None = None


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
