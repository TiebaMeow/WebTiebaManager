from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from cashews import Cache
from cashews.backends.interface import NOT_EXIST, UNLIMITED

from src.control import Controller

from .event import AsyncEvent

ClearCache = AsyncEvent[None]()
Key = str
PossibleKey = str | int | float


class CacheCleaner:
    _clear_cache_scheduler: AsyncIOScheduler | None = None
    _clear_cache_time: str = "04:00"

    @classmethod
    def initialize(cls):
        if cls._clear_cache_scheduler is None:
            cls._clear_cache_scheduler = AsyncIOScheduler()

    @classmethod
    async def clear_cache(cls):
        await ClearCache.broadcast(None)

    @classmethod
    def setup_job(cls):
        hour, minute = map(int, cls._clear_cache_time.split(":"))
        cls._clear_cache_scheduler.add_job(  # type: ignore
            cls.clear_cache,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="clear_cache_job",
            replace_existing=True,
            executor="default",
            misfire_grace_time=300,
        )

    @classmethod
    def start(cls, _=None):
        cls.initialize()
        cls.setup_job()
        cls._clear_cache_scheduler.start()  # type: ignore

    @classmethod
    def stop(cls, _=None):
        if cls._clear_cache_scheduler and cls._clear_cache_scheduler.running:
            cls._clear_cache_scheduler.shutdown()

    @classmethod
    def update_clear_cache_time(cls, _=None):
        if Controller.config.cleanup_time != cls._clear_cache_time:
            cls._clear_cache_time = Controller.config.cleanup_time
            cls.setup_job()


Controller.Start.on(CacheCleaner.start)
Controller.Stop.on(CacheCleaner.stop)
Controller.SystemConfigChange.on(CacheCleaner.update_clear_cache_time)


class ExpireCache[T]:
    """
    cashews 封装，兼容原有接口

    Attributes:
        directory (Path | None): 磁盘缓存路径，为 None 则使用内存缓存
        expire_time (int | None): 缓存过期时间，为 None 则不设置过期时间
        mem_max_size (int): 内存缓存最大数量，仅在 directory 为 None 时生效
    """

    def __init__(
        self,
        directory: Path | None = None,
        *,
        expire_time: int | None = 86400,
        mem_max_size: int = 10000,
    ):
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

    def fmt_key(self, key: PossibleKey) -> Key:
        return str(key)

    async def set(self, key: PossibleKey, data: T):
        await self.cache.set(self.fmt_key(key), self.serialize_data(data), expire=self.expire_time)

    async def get(self, key: PossibleKey) -> T | None:
        data = await self.cache.get(self.fmt_key(key), default=None)
        if data is not None:
            return self.deserialize_data(data)
        return None

    async def delete(self, key: PossibleKey) -> bool:
        return await self.cache.delete(self.fmt_key(key))

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
