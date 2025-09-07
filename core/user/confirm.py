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

    @staticmethod
    def serialize_data(data):
        return data.model_dump()

    @staticmethod
    def unserialize_data(data: dict):
        return ConfirmData.model_validate(data)
