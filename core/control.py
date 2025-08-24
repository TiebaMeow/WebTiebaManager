from .util.event import AsyncEvent
from .config import config
from .typedef import Content


class Controller:
    Start = AsyncEvent[None]()
    Stop = AsyncEvent[None]()
    MainConfigChange = AsyncEvent[None]()
    DispatchContent = AsyncEvent[Content]()

    config = config
    running: bool = False

    @classmethod
    async def start(cls):
        cls.running = True
        await cls.Start.broadcast(None)
