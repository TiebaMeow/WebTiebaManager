import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from functools import wraps
from pathlib import Path

import diskcache

from core.control import Controller

from .event import AsyncEvent

ClearCache = AsyncEvent[None]()


class CacheCleaner:
    _clear_cache_time: str = "04:00"
    _clear_cache_task = None

    @classmethod
    async def clear_cache_loop(cls):
        clear_cache_time = cls._clear_cache_time
        while True:
            now = datetime.now()
            target = now.replace(
                hour=int(clear_cache_time.split(":")[0]),
                minute=int(clear_cache_time.split(":")[1]),
                second=0,
                microsecond=0,
            )
            if now > target:
                target = target.replace(day=now.day + 1)
                try:
                    target = target.replace(day=now.day + 1)
                except ValueError:
                    # 跨月处理
                    if now.month == 12:
                        target = target.replace(year=now.year + 1, month=1, day=1)
                    else:
                        target = target.replace(month=now.month + 1, day=1)

            wait_seconds = (target - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            await ClearCache.broadcast(None)

    @classmethod
    def start(cls, _=None):
        cls._clear_cache_time = Controller.config.cleanup_time
        cls._clear_cache_task = asyncio.create_task(cls.clear_cache_loop())

    @classmethod
    def stop(cls, _=None):
        if cls._clear_cache_task:
            cls._clear_cache_task.cancel()
            cls._clear_cache_task = None

    @classmethod
    def update_clear_cache_time(cls, _=None):
        if Controller.config.cleanup_time != cls._clear_cache_time:
            cls._clear_cache_time = Controller.config.cleanup_time
            if cls._clear_cache_task:
                cls._clear_cache_task.cancel()
                cls._clear_cache_task = asyncio.create_task(cls.clear_cache_loop())


Controller.Start.on(CacheCleaner.start)
Controller.Stop.on(CacheCleaner.stop)
Controller.SystemConfigChange.on(CacheCleaner.update_clear_cache_time)


class ExpireCache[T]:
    """
    dickcache 封装，兼容原有接口
    """

    def __init__(self, directory: str | Path, expire_time: int = 86400):
        self.expire_time = expire_time
        self.cache = diskcache.Cache(directory=directory)
        self.listener = ClearCache.on(self.expire)

    def stop(self):
        self.listener.un_register()
        self.cache.close()

    def set(self, key, data: T):
        self.cache.set(key, self.serialize_data(data), expire=self.expire_time)

    def get(self, key) -> T | None:
        data = self.cache.get(key, default=None)
        if data is not None:
            return self.deserialize_data(data)

    def delete(self, key) -> bool:
        return self.cache.delete(key)

    def expire(self, _=None):
        self.cache.expire()

    def clear(self) -> None:
        self.cache.clear()

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

            return async_wrapper  # type: ignore
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

    def set_expire_time(self, new_expire_time: int):
        expire_delta = new_expire_time - self.expire_time

        # logic 1: 变更所有已缓存项目的expire
        # if expire_delta < 0:
        #     self.cache.expire(now=time.time() + expire_delta)
        # Logic 1 end

        # logic 2: 变更所有已缓存项目的expire
        now = time.time()
        for key in self.cache.iterkeys():
            data = self.cache.get(key, expire_time=True)
            if data is None:
                continue

            expire: int = data[1]  # type: ignore
            new_expire = now - (expire + expire_delta)
            if new_expire <= 0:
                self.cache.delete(key)
            else:
                self.cache.touch(key, expire=new_expire)
        # Logic 2 end

        self.expire_time = new_expire_time

    @staticmethod
    def serialize_data(data: T):
        return data

    @staticmethod
    def deserialize_data(data) -> T:
        return data

    def values(self) -> list[T]:
        """
        返回所有缓存的反序列化值列表
        """
        result = []
        for key in self.cache.iterkeys():
            data = self.cache.get(key, default=None)
            if data is not None:
                result.append(self.deserialize_data(data))
        return result
