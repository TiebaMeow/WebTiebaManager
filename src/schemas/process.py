from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tieba import Content


class ProcessObject[T]:
    content: Content
    data: T  # 处理过程中附加的数据

    def __init__(self, content: Content, data: T | None = None) -> None:
        self.content = content
        self.data = data or {}  # type: ignore
