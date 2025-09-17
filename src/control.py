from src.util.logging import system_logger

from .config import SystemConfig, read_config, write_config
from .constance import SYSTEM_CONFIG_PATH
from .typedef import Content, UpdateEventData
from .util.event import AsyncEvent


class Controller:
    Start = AsyncEvent[None]()
    Stop = AsyncEvent[None]()
    SystemConfigChange = AsyncEvent[UpdateEventData[SystemConfig]]()
    DispatchContent = AsyncEvent[Content]()

    config: SystemConfig = read_config(SYSTEM_CONFIG_PATH, SystemConfig)
    running: bool = False

    @classmethod
    async def start(cls):
        if cls.running:
            return

        system_logger.info("系统开始运行")
        cls.running = True
        await cls.Start.broadcast(None)

    @classmethod
    async def stop(cls):
        if not cls.running:
            return

        cls.running = False
        await cls.Stop.broadcast(None)
        system_logger.info("系统停止运行")

    @classmethod
    async def update_config(cls, new_config: SystemConfig):
        if cls.config == new_config:
            return

        old_config = cls.config
        cls.config = new_config
        write_config(new_config, SYSTEM_CONFIG_PATH)
        await cls.SystemConfigChange.broadcast(UpdateEventData(old=old_config, new=new_config))
        system_logger.info("系统配置已更改")
