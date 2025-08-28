from .config import SystemConfig, system_config, write_config
from .typedef import Content
from .util.event import AsyncEvent


class Controller:
    Start = AsyncEvent[None]()
    Stop = AsyncEvent[None]()
    SystemConfigChange = AsyncEvent[None]()
    DispatchContent = AsyncEvent[Content]()

    config: SystemConfig
    running: bool = False

    @classmethod
    async def start(cls):
        cls.running = True
        await cls.Start.broadcast(None)

    @classmethod
    async def stop(cls):
        cls.running = False
        await cls.Stop.broadcast(None)

    @classmethod
    async def update_config(cls, new_config: SystemConfig):
        cls.config = new_config
        write_config(new_config)
        await cls.SystemConfigChange.broadcast(None)


Controller.config = system_config
