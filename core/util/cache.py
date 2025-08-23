import os
import time
import json
import asyncio
from functools import wraps
from typing import TypeVar, Generic, Callable

T = TypeVar("T")


class ExpireCache(Generic[T]):
    """
    注意：虽然key可以为多种类型，但实际储存时仍为str（json限制）
    这可能导致意外的key重复，如 '123'(str) 与 123(int)，请只使用同一类型的key
    """
    POSSIBLE_KEY = str | int | float

    def __init__(
        self,
        expire: int = 86400,
        clear_after_set: bool = True,
        path: os.PathLike | None = None,
    ):
        self.expire: int = expire
        self.data: dict[str | int, T] = {}
        self.key: dict[str, float] = {}
        self.path = path

        if clear_after_set:

            def set(key: ExpireCache.POSSIBLE_KEY, data: T):
                ExpireCache.set(self, key, data)
                self.clean()

            self.set = set

    @staticmethod
    def format_key(key: POSSIBLE_KEY) -> str:
        return str(key)

    def set(self, key: POSSIBLE_KEY, data: T):
        key = self.format_key(key)
        self.data[key] = data
        self.key[key] = time.time()

    def get(self, key: POSSIBLE_KEY) -> T | None:
        key = self.format_key(key)
        if key in self.data:
            if time.time() - self.key[key] > self.expire:
                self.data.pop(key)
                self.key.pop(key)
            else:
                return self.data[key]

    def delete(self, key: POSSIBLE_KEY) -> bool:
        key = self.format_key(key)
        if key in self.data:
            self.data.pop(key)
            self.key.pop(key)
            return True

        return False

    def clean(self) -> int:
        cleaned = 0
        now = time.time()

        for key, create_time in self.key.copy().items():
            if now - create_time > self.expire:
                self.data.pop(key)
                self.key.pop(key)
                cleaned += 1

        return cleaned

    def clear(self) -> None:
        self.data.clear()
        self.key.clear()

    def wrap(self, func: Callable[..., T]) -> Callable[..., T]:
        if asyncio.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs) -> T:
                key = f"{func.__name__}_{args}_{kwargs}"
                if (data := self.get(key)) is not None:
                    return data
                result = await func(*args, **kwargs)
                self.set(key, result)
                return result

            return async_wrapper # type: ignore
        else:

            @wraps(func)
            def wrapper(*args, **kwargs) -> T:
                key = f"{func.__name__}_{args}_{kwargs}"
                if (data := self.get(key)) is not None:
                    return data
                result = func(*args, **kwargs)
                self.set(key, result)
                return result

            return wrapper

    @staticmethod
    def serialize_data(data: T):
        return data

    @staticmethod
    def unserialize_data(data: T):
        return data

    def save_data(self) -> None:
        if self.path:
            data = {
                "data": {k: self.serialize_data(v) for k, v in self.data.items()},
                "key": self.key,
            }
            with open(self.path, "wt", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def load_data(self) -> None:
        if self.path and os.path.exists(self.path):
            with open(self.path, "rt", encoding="utf-8") as f:
                data = json.load(f)
                if not data:
                    return
                self.key = data["key"]
                self.data = {
                    k: self.unserialize_data(v) for k, v in data["data"].items()
                }
