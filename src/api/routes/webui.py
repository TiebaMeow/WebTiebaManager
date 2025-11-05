import asyncio
from pathlib import Path

import aiofiles
from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.core.constants import CACHE_DIR, DEV, MAIN_SERVER, PROGRAM_VERSION, RESOURCE_DIR, WEB_UI_CODE
from src.utils.anonymous import AnonymousAiohttp
from src.utils.logging import system_logger
from src.utils.tools import Timer

from ..server import Server, app

WEBUI_CACHE = CACHE_DIR / "webui"
WEBUI_CACHE.mkdir(parents=True, exist_ok=True)
WEBUI_BASE = MAIN_SERVER + f"/webui/{WEB_UI_CODE}"

DOWNLOADABLE_RESOURCES = {"Sarasa-Mono-SC-Nerd.woff2"}
VALID_RESOURCES = {"Sarasa-Mono-SC-Nerd.woff2"}
downloading_resources = {}


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
    except Exception as e:
        system_logger.error(f"网页资源反向代理失败: {e}")
        raise HTTPException(status_code=502, detail="Bad Gateway") from e


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
