from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.constance import CONFIRM_EXPIRE
from core.typedef import Content
from core.util.cache import ExpireCache


class ConfirmData(BaseModel):
    content: Content
    data: dict
    operations: str | list[dict[str, Any]]
    process_time: int
    rule_set_name: str


class ConfirmCache(ExpireCache[ConfirmData]):
    def __init__(self, user_dir: Path, expire: int = CONFIRM_EXPIRE, clear_after_set: bool = True):
        path = user_dir / "confirm_cache.json"
        super().__init__(expire, clear_after_set, path)
        self.load_data()

    def set(self, key: str | int | float, data: ConfirmData):
        result = super().set(key, data)
        self.save_data()
        return result

    def delete(self, key: str | int | float) -> bool:
        result = super().delete(key)
        self.save_data()
        return result
