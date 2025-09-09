from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.constance import CONFIRM_EXPIRE
from core.typedef import Content
from core.util.cache import ExpireCache


class ConfirmSimpleData(BaseModel):
    content: Content
    process_time: int
    rule_set_name: str


class ConfirmData(ConfirmSimpleData):
    data: dict
    operations: str | list[dict[str, Any]]

    @property
    def simple(self):
        return ConfirmSimpleData(content=self.content, process_time=self.process_time, rule_set_name=self.rule_set_name)


class ConfirmCache(ExpireCache[ConfirmData]):
    """确认缓存，泛型为 ConfirmData"""

    def __init__(self, user_dir: Path, expire_time: int = CONFIRM_EXPIRE):
        super().__init__(directory=user_dir / "confirm", expire_time=expire_time)
