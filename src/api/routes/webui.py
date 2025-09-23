import asyncio
from pathlib import Path

import aiofiles
from fastapi import Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.core.constants import DEV, MAIN_SERVER, PROGRAM_VERSION, RESOURCE_DIR, WEB_UI_VERSION
from src.utils.anonymous import AnonymousAiohttp
from src.utils.logging import system_logger
from src.utils.tools import Timer

from ..server import Server, app

WEBUI_BASE = MAIN_SERVER + f"/webui/{WEB_UI_VERSION}"

DOWNLOADABLE_RESOURCES = {"Sarasa-Mono-SC-Nerd.woff2"}
VALID_RESOURCES = {"Sarasa-Mono-SC-Nerd.woff2"}
downloading_resources = {}


async def reverse_proxy(url: str, request: Request, raw=False):
    session = await AnonymousAiohttp.session()
    headers = {key: value for key, value in request.headers.items() if key != "host"}
    async with session.get(url, headers=headers) as resp:
        data = await resp.read()
        headers = dict(resp.headers)

        if raw:
            return data, resp.status, headers

        for h in ["Transfer-Encoding", "Content-Encoding", "Server", "Date"]:
            headers.pop(h, None)
        return data, resp.status, headers


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
    content, status_code, headers = await reverse_proxy(f"{WEBUI_BASE}/index.html", request)
    if Server.need_initialize():
        content = content.replace(b"</head>", b'<script>location.href="/#/initialize"</script></head>')
        headers["Content-Length"] = str(len(content))
        headers["Cache-Control"] = "no-store"
    return Response(content=content, status_code=status_code, headers=headers)


@app.get("/assets/{path:path}", tags=["webui"])
async def assets(path: str, request: Request):
    content, status_code, headers = await reverse_proxy(f"{WEBUI_BASE}/assets/{path}", request)
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
