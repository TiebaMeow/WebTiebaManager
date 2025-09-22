from __future__ import annotations

from typing import TYPE_CHECKING

from src.schemas.event import UpdateEventData
from src.schemas.tieba import Content
from src.utils.config import read_config, write_config
from src.utils.event import AsyncEvent
from src.utils.logging import system_logger

from .constants import SYSTEM_CONFIG_PATH

if TYPE_CHECKING:
    from .config import SystemConfig  # noqa: TC004


class Controller:
    Start = AsyncEvent[None]()
    Stop = AsyncEvent[None]()
    DispatchContent = AsyncEvent[Content]()
    SystemConfigChange: AsyncEvent[UpdateEventData[SystemConfig]] = AsyncEvent()
    config: SystemConfig
    initialized: bool = False

    running: bool = False

    @classmethod
    def initialize(cls) -> bool:
        if cls.initialized:
            return False

        """
        在所有包导入后调用，预加载配置
        """
        try:
            from .config import SystemConfig  # noqa: TC001
        except Exception:
            system_logger.exception("导入 SystemConfig 失败，可能是循环导入导致")
            raise

        if not getattr(cls, "config", None):
            cls.config = read_config(SYSTEM_CONFIG_PATH, SystemConfig)

        cls.initialized = True
        return True

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
