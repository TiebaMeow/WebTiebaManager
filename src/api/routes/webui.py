import asyncio
import mimetypes
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import aiofiles
import aiohttp
from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.core.constants import (
    CACHE_DIR,
    DEV,
    MAIN_SERVER,
    PROGRAM_VERSION,
    RESOURCE_DIR,
    WEB_UI_CODE,
    WEBUI_DIR_OVERRIDE,
    WEBUI_SERVER,
    WEBUI_ZIP_OVERRIDE,
)
from src.utils.anonymous import AnonymousAiohttp
from src.utils.logging import system_logger
from src.utils.tools import Timer

from ..server import Server, app

WEBUI_CACHE = CACHE_DIR / "webui"
WEBUI_CACHE.mkdir(parents=True, exist_ok=True)

DOWNLOADABLE_RESOURCES = {"Sarasa-Mono-SC-Nerd.woff2"}
VALID_RESOURCES = {"Sarasa-Mono-SC-Nerd.woff2"}
downloading_resources = {}

if WEBUI_SERVER:
    WEBUI_BASE = WEBUI_SERVER.rstrip("/")
    system_logger.info(f"使用自定义 WebUI 服务器: {WEBUI_SERVER}")
else:
    WEBUI_BASE = MAIN_SERVER + f"/webui/{WEB_UI_CODE}"


LOCAL_WEBUI_DIR = None
if WEBUI_DIR_OVERRIDE:
    if WEBUI_DIR_OVERRIDE.is_dir():
        LOCAL_WEBUI_DIR = WEBUI_DIR_OVERRIDE
        system_logger.info(f"优先从本地 WebUI 目录加载资源: {WEBUI_DIR_OVERRIDE}")
    else:
        system_logger.warning(f"指定的 WebUI 目录不存在或不可访问: {WEBUI_DIR_OVERRIDE}")

LOCAL_WEBUI_ZIP = None
if WEBUI_ZIP_OVERRIDE:
    if WEBUI_ZIP_OVERRIDE.is_file():
        LOCAL_WEBUI_ZIP = WEBUI_ZIP_OVERRIDE
        system_logger.info(f"启用 WebUI 压缩包资源: {WEBUI_ZIP_OVERRIDE}")
    else:
        system_logger.warning(f"指定的 WebUI 压缩包不存在或不可访问: {WEBUI_ZIP_OVERRIDE}")

LOCAL_OVERRIDE_ENABLED = LOCAL_WEBUI_DIR is not None or LOCAL_WEBUI_ZIP is not None


@dataclass
class LocalAsset:
    data: bytes
    media_type: str | None


def _normalize_relative_path(rel_path: str) -> str | None:
    raw = rel_path.replace("\\", "/")
    raw_parts = raw.split("/")
    if any(part == ".." for part in raw_parts):
        return None

    normalized = raw.lstrip("/")
    safe_path = PurePosixPath(normalized)

    return str(safe_path)


async def _read_from_local_dir(normalized_path: str) -> LocalAsset | None:
    if LOCAL_WEBUI_DIR is None:
        return None

    base_dir = LOCAL_WEBUI_DIR.resolve()

    try:
        file_path = (base_dir / normalized_path).resolve(strict=True)
    except FileNotFoundError:
        return None

    if not file_path.is_relative_to(base_dir) or not file_path.is_file():
        return None

    async with aiofiles.open(file_path, "rb") as f:
        data = await f.read()

    media_type = mimetypes.guess_type(file_path.name)[0]
    return LocalAsset(data=data, media_type=media_type)


async def _read_from_zip(normalized_path: str) -> LocalAsset | None:
    zip_path = LOCAL_WEBUI_ZIP
    if zip_path is None:
        return None

    def _load_from_zip() -> bytes | None:
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                with archive.open(normalized_path) as file:
                    return file.read()
        except FileNotFoundError:
            system_logger.error(f"WebUI 压缩包在运行时丢失: {zip_path}")
            return None
        except KeyError:
            system_logger.error(f"WebUI 资源在压缩包中不存在: {normalized_path} in {zip_path}")
            return None
        except (zipfile.BadZipFile, OSError):
            system_logger.error(f"WebUI 压缩包损坏或无法读取: {zip_path}")
            return None

    data = await asyncio.to_thread(_load_from_zip)
    if data is None:
        return None

    media_type = mimetypes.guess_type(PurePosixPath(normalized_path).name)[0]
    return LocalAsset(data=data, media_type=media_type)


async def load_local_asset(rel_path: str) -> LocalAsset | None:
    normalized_path = _normalize_relative_path(rel_path)
    if not normalized_path:
        return None

    asset = await _read_from_local_dir(normalized_path)
    if asset:
        return asset

    return await _read_from_zip(normalized_path)


async def reverse_proxy(url: str, request: Request, raw=False):
    system_logger.debug(f"反向代理请求: {url}")
    try:
        session = await AnonymousAiohttp.session()
        headers = {key: value for key, value in request.headers.items() if key != "host"}
        async with session.get(url, headers=headers) as resp:
            data = await resp.read()
            headers = dict(resp.headers)

            if raw:
                return data, resp.status, headers

            for h in ["Transfer-Encoding", "Content-Encoding", "Server", "Date", "Content-Length"]:
                headers.pop(h, None)
            return data, resp.status, headers
    except TimeoutError as e:
        system_logger.error(f"网页资源请求超时: {e}")
        raise HTTPException(status_code=504, detail="Gateway Timeout") from e
    except aiohttp.ClientError as e:
        system_logger.error(f"网页资源请求失败: {e}")
        raise HTTPException(status_code=502, detail="Bad Gateway") from e
    except Exception as e:
        system_logger.error(f"网页资源反向代理内部错误: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error") from e


async def download_resource(path: Path):
    if path in downloading_resources:
        event = downloading_resources[path]
        await event.wait()
        if path.exists():
            async with aiofiles.open(path, "rb") as f:
                return await f.read()
        return None

    system_logger.info(f"正在下载资源文件: {path.name}")
    url = f"{MAIN_SERVER}/webui/resources/{path.name}"
    session = await AnonymousAiohttp.session()
    event = asyncio.Event()
    downloading_resources[path] = event

    try:
        with Timer() as t:
            async with session.get(url) as resp:
                if resp.status != 200:
                    system_logger.error(f"资源文件下载失败: {path.name} (HTTP {resp.status})")
                    return None
                data = await resp.read()

                path.parent.mkdir(parents=True, exist_ok=True)

                async with aiofiles.open(path, "wb") as f:
                    await f.write(data)

                system_logger.info(f"资源文件下载完成: {path.name} ({t.elapsed:.2f}s)")
                return data
    finally:
        event.set()
        downloading_resources.pop(path, None)


@app.get("/", tags=["webui"])
async def index(request: Request):
    cache_path = WEBUI_CACHE / "index.html"

    if LOCAL_OVERRIDE_ENABLED:
        local_asset = await load_local_asset("index.html")
        if local_asset:
            content = local_asset.data
            headers = {}

            if Server.need_initialize():
                content = content.replace(b"</head>", b'<script>location.href="/#/initialize"</script></head>')
                headers["Cache-Control"] = "no-store"

            return Response(content=content, media_type=local_asset.media_type or "text/html", headers=headers)

    try:
        content, status_code, headers = await reverse_proxy(f"{WEBUI_BASE}/index.html", request)
        if status_code == 200:
            # 缓存成功的请求
            async with aiofiles.open(cache_path, "wb") as f:
                await f.write(content)

    except Exception:
        if not cache_path.exists():
            return Response(status_code=503, content="Service Unavailable")

        system_logger.warning("无法连接到 WebUI 服务器，使用缓存的文件")
        return FileResponse(cache_path)

    if Server.need_initialize():
        content = content.replace(b"</head>", b'<script>location.href="/#/initialize"</script></head>')
        headers["Cache-Control"] = "no-store"

    return Response(content=content, status_code=status_code, headers=headers)


@app.get("/assets/{path:path}", tags=["webui"])
async def assets(path: str, request: Request):
    cache_headers = {"Cache-Control": "max-age=2592000"}

    if LOCAL_OVERRIDE_ENABLED:
        local_asset = await load_local_asset(f"assets/{path}")
        if local_asset:
            media_type = local_asset.media_type or "application/octet-stream"
            return Response(content=local_asset.data, media_type=media_type, headers=cache_headers)

    # assets下的文件不会更新，所以优先使用本地缓存
    cache_path = WEBUI_CACHE / path
    if cache_path.exists():
        return FileResponse(cache_path, headers=cache_headers)

    content, status_code, headers = await reverse_proxy(f"{WEBUI_BASE}/assets/{path}", request)
    headers.update(cache_headers)
    if status_code == 200:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(cache_path, "wb") as f:
            await f.write(content)

    return Response(content=content, status_code=status_code, headers=headers)


@app.get("/favicon.ico", tags=["webui"])
async def favicon(request: Request):
    if LOCAL_OVERRIDE_ENABLED:
        local_asset = await load_local_asset("favicon.ico")
        if local_asset:
            media_type = local_asset.media_type or "image/x-icon"
            return Response(content=local_asset.data, media_type=media_type)

    content, status_code, headers = await reverse_proxy(f"{WEBUI_BASE}/favicon.ico", request)
    return Response(content=content, status_code=status_code, headers=headers)


class ServerInfo(BaseModel):
    version: str
    need_initialize: bool


@app.get("/api/info", tags=["webui"])
async def webui_info() -> ServerInfo:
    return ServerInfo(version=PROGRAM_VERSION, need_initialize=Server.need_initialize())


@app.get("/resources/{path:path}", tags=["webui"])
async def resources(path: str, request: Request):
    if path not in VALID_RESOURCES and not DEV:
        return Response(status_code=403, content="Forbidden")

    if ".." in path or path.startswith("/") or Path(path).is_absolute():
        return Response(status_code=400, content="Bad Request")

    file_path = (RESOURCE_DIR / path).resolve()

    if not file_path.is_relative_to(RESOURCE_DIR.resolve()):
        return Response(status_code=400, content="Bad Request")

    if not file_path.exists() or not file_path.is_file():
        if path in DOWNLOADABLE_RESOURCES:
            data = await download_resource(file_path)
            if data is None:
                return Response(status_code=404, content="Not Found")
            return Response(content=data, media_type="application/octet-stream")

        return Response(status_code=404, content="Not Found")

    return FileResponse(file_path)
