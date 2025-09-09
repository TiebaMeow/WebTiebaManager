import asyncio
from datetime import datetime
from pathlib import Path

from cashews import Cache
from cashews.backends.interface import NOT_EXIST, UNLIMITED

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
    cashews 封装，兼容原有接口
    """

    def __init__(self, directory: Path | None = None, *, expire_time: int | None = 86400, mem_max_size: int = 10000):
        self.cache = Cache()
        self.expire_time = expire_time
        if directory is None:
            self.cache.setup(f"mem://?size={mem_max_size}")
        else:
            directory_str = directory.resolve().as_posix()
            self.cache.setup(f"disk://?shards=0&directory={directory_str}")
        self.listener = ClearCache.on(self.expire)

    async def stop(self):
        self.listener.un_register()
        await self.cache.close()

    async def set(self, key, data: T):
        await self.cache.set(key, self.serialize_data(data), expire=self.expire_time)

    async def get(self, key) -> T | None:
        data = await self.cache.get(key, default=None)
        if data is not None:
            return self.deserialize_data(data)
        return None

    async def delete(self, key) -> bool:
        return await self.cache.delete(key)

    async def expire(self, _=None) -> None:
        expired_keys = set()
        async for key in self.cache.scan("*"):
            expire = await self.cache.get_expire(key)
            if expire == NOT_EXIST:
                expired_keys.add(key)
        if expired_keys:
            await self.cache.delete(*expired_keys)

    async def clear(self) -> None:
        await self.cache.clear()

    async def set_expire_time(self, new_expire_time: int):
        expire_time = self.expire_time or 0
        expire_delta = new_expire_time - expire_time

        # logic 1: 变更所有已缓存项目的expire
        # if expire_delta < 0:
        #     self.cache.expire(now=time.time() + expire_delta)
        # Logic 1 end

        # logic 2: 变更所有已缓存项目的expire
        async for key in self.cache.scan("*"):
            expire = await self.cache.get_expire(key)
            if expire == UNLIMITED:
                continue
            if expire == NOT_EXIST:
                await self.cache.delete(key)
                continue

            new_expire = expire + expire_delta
            if new_expire <= 0:
                await self.cache.delete(key)
            else:
                await self.cache.expire(key, timeout=new_expire)
        # Logic 2 end

        self.expire_time = new_expire_time

    @staticmethod
    def serialize_data(data: T):
        return data

    @staticmethod
    def deserialize_data(data) -> T:
        return data

    async def values(self) -> list[T]:
        """
        返回所有缓存的反序列化值列表
        """
        result = [self.deserialize_data(data) async for _, data in self.cache.get_match("*") if data is not None]
        return result
