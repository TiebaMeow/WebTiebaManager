import asyncio
import ssl

import aiohttp
from packaging.version import parse

from src.core.constants import IS_EXE, MAIN_SERVER, PROGRAM_VERSION, PROJECT_ROOT

from .anonymous import AnonymousAiohttp
from .logging import exception_logger, system_logger

GITHUB_RELEASES_API = "https://api.github.com/repos/TiebaMeow/WebTiebaManager/releases/latest"
RELEASE_URL = "https://github.com/TiebaMeow/WebTiebaManager/releases/latest"

IGNORE_EXCEPTIONS = (
    asyncio.TimeoutError,
    aiohttp.ClientConnectionError,
    aiohttp.ClientPayloadError,
    ssl.SSLError,
    ssl.CertificateError,
)


async def get_latest_version() -> str | None:
    session = await AnonymousAiohttp.session()
    with exception_logger("获取最新版本信息失败", ignore_exceptions=IGNORE_EXCEPTIONS):
        # 优先尝试从github直接获取最新版本
        async with session.get(GITHUB_RELEASES_API) as resp:
            if resp.status == 200:
                data = await resp.json()
                latest_version = data.get("tag_name")
                if latest_version:
                    return latest_version.lstrip("v")
                else:
                    system_logger.warning("未能在Github响应中找到版本信息")

    with exception_logger("获取最新版本信息失败", ignore_exceptions=IGNORE_EXCEPTIONS):
        # 其次尝试从备用服务器获取最新版本
        async with session.get(f"{MAIN_SERVER}/version") as resp:
            if resp.status == 200:
                data = await resp.json()
                latest_version = data.get("version")
                if latest_version:
                    return latest_version.lstrip("v")
                else:
                    system_logger.warning("未能在备用服务器响应中找到版本信息")

    system_logger.warning("无法获取最新版本信息")
    return None


async def check_for_updates() -> None:
    latest_version = await get_latest_version()
    if latest_version is None:
        return

    if parse(latest_version) > parse(PROGRAM_VERSION):
        system_logger.info(f"检测到新版本: v{latest_version}")
        if IS_EXE:
            system_logger.info(f"请访问 {RELEASE_URL} 下载最新版本")
        else:
            # 检测是否通过 git 部署
            if (PROJECT_ROOT / ".git").is_dir():
                system_logger.info("请运行 'git pull' 以更新到最新版本")
            else:
                system_logger.info(f"请访问 {RELEASE_URL} 下载最新版本")
