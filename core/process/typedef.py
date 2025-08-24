from typing import Generic, TypeVar

from ..typedef import Content

T = TypeVar("T")


class ProcessObject(Generic[T]):
    content: Content
    data: T  # 处理过程中附加的数据

    def __init__(self, content: Content, data: T | None = None) -> None:
        self.content = content
        self.data = data or {}  # type: ignore
