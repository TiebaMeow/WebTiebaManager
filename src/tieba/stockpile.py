from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel

from src.utils.logging import system_logger

if TYPE_CHECKING:
    from src.user.user import User


class StockpileResult(BaseModel):
    """单次囤货操作的结果"""

    forum: str
    success: bool
    message: str
    timestamp: datetime


class StockpileScheduler:
    """
    自动囤货调度器

    管理所有用户的囤货定时任务。每个启用了自动囤货功能的用户都会拥有一个独立的
    定时任务，按照其配置的时间（cron）在指定的贴吧（forums）中执行囤货操作。
    """

    _scheduler: AsyncIOScheduler | None = None

    @classmethod
    def initialize(cls) -> None:
        if cls._scheduler is None:
            cls._scheduler = AsyncIOScheduler()

    @classmethod
    def setup_jobs(cls, _=None) -> None:
        """
        根据当前所有用户配置重建囤货定时任务。

        移除所有已有的囤货任务，再根据用户配置重新创建。
        每次用户配置变更时应调用此方法。
        """
        from src.user.manager import UserManager

        cls.initialize()
        assert cls._scheduler is not None

        for job in cls._scheduler.get_jobs():
            if job.id.startswith("stockpile_"):
                job.remove()

        for username, user in UserManager.users.items():
            cfg = user.config.stockpile
            if not cfg.enabled:
                continue
            hour, minute = map(int, cfg.cron.split(":"))
            cls._scheduler.add_job(
                cls.run_for_user,
                trigger=CronTrigger(hour=hour, minute=minute),
                id=f"stockpile_{username}",
                args=[username],
                replace_existing=True,
                misfire_grace_time=300,
            )
            system_logger.debug(f"已为用户 {username} 创建自动囤货任务，执行时间: {cfg.cron}")

    @classmethod
    async def run_for_user(cls, username: str) -> None:
        """执行指定用户的囤货任务"""
        from src.user.manager import UserManager

        user = UserManager.get_user(username)
        if user is None:
            system_logger.warning(f"自动囤货: 用户 {username} 不存在，跳过任务")
            return

        cfg = user.config.stockpile
        if not cfg.enabled:
            return

        forums = cfg.forums or ([user.fname] if user.fname else [])
        if not forums:
            system_logger.warning(f"自动囤货: 用户 {username} 未设置目标贴吧，跳过任务")
            return

        system_logger.info(f"开始执行用户 {username} 的自动囤货任务，目标贴吧: {forums}")

        results: list[StockpileResult] = []
        for forum in forums:
            result = await cls.perform_stockpile(user, forum)
            results.append(result)

        success_count = sum(1 for r in results if r.success)
        system_logger.info(f"用户 {username} 自动囤货任务完成，成功: {success_count}/{len(results)}")

    @classmethod
    async def perform_stockpile(cls, user: User, forum: str) -> StockpileResult:
        """
        在指定贴吧对指定用户执行一次囤货操作。

        TODO: 使用 aiotieba 客户端实现具体的囤货逻辑（例如签到、积分收集等）。
        """
        timestamp = datetime.now()
        try:
            # TODO: 调用 user.client 的相关接口完成囤货操作
            system_logger.debug(f"用户 {user.username} 在贴吧 {forum} 执行自动囤货")
            return StockpileResult(forum=forum, success=True, message="操作成功", timestamp=timestamp)
        except Exception as e:
            system_logger.error(f"用户 {user.username} 在贴吧 {forum} 自动囤货失败: {e}")
            return StockpileResult(forum=forum, success=False, message=str(e), timestamp=timestamp)

    @classmethod
    def start(cls, _=None) -> None:
        cls.initialize()
        cls.setup_jobs()
        assert cls._scheduler is not None
        cls._scheduler.start()
        system_logger.info("自动囤货调度器已启动")

    @classmethod
    def stop(cls, _=None) -> None:
        if cls._scheduler and cls._scheduler.running:
            cls._scheduler.shutdown()
            system_logger.debug("自动囤货调度器已停止")
