from .util.event import AsyncEvent
from .config import config
from .typedef import Content


class Controller:
    Start = AsyncEvent[None]()
    Stop = AsyncEvent[None]()
    MainConfigChange = AsyncEvent[None]()
    DispatchContent = AsyncEvent[Content]()

    config = config

    @classmethod
    async def start(cls):
        await cls.Start.broadcast(None)
