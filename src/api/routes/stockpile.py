from __future__ import annotations

import asyncio

from src.core.config import StockpileConfig  # noqa: TC001
from src.tieba.stockpile import StockpileScheduler
from src.user.manager import UserManager
from src.utils.logging import system_logger

from ..auth import current_user_depends, system_access_depends  # noqa: TC001
from ..server import BaseResponse, app


@app.get("/api/stockpile/get_config", tags=["stockpile"])
async def get_stockpile_config(user: current_user_depends) -> BaseResponse[StockpileConfig]:
    """获取当前用户的自动囤货任务配置"""
    return BaseResponse(data=user.config.stockpile)


@app.post("/api/stockpile/set_config", tags=["stockpile"])
async def set_stockpile_config(
    user: current_user_depends,
    system_access: system_access_depends,
    req: StockpileConfig,
) -> BaseResponse[bool]:
    """更新当前用户的自动囤货任务配置"""
    config = user.config.model_copy(deep=True)
    config.stockpile = req
    try:
        await UserManager.update_config(config, system_access=system_access)
    except PermissionError as e:
        return BaseResponse(data=False, message=str(e), code=403)

    return BaseResponse(data=True)


def _log_task_error(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()):
        system_logger.error(f"自动囤货后台任务异常: {exc}")


@app.post("/api/stockpile/trigger", tags=["stockpile"])
async def trigger_stockpile(user: current_user_depends) -> BaseResponse[bool]:
    """手动立即触发一次当前用户的囤货任务"""
    task = asyncio.create_task(StockpileScheduler.run_for_user(user.username))
    task.add_done_callback(_log_task_error)
    return BaseResponse(data=True, message="囤货任务已触发，请稍后查看日志")
