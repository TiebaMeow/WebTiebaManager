from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.core.constants import MAIN_SERVER, PROGRAM_VERSION, RESOURCE_DIR, WEB_UI_VERSION
from src.utils.anonymous import AnonymousAiohttp

from ..server import Server, app

WEBUI_BASE = MAIN_SERVER + f"/webui/{WEB_UI_VERSION}"


async def reverse_proxy(url: str, request: Request, raw=False):
    client = await AnonymousAiohttp.session()
    headers = {key: value for key, value in request.headers.items() if key != "host"}
    async with client.get(url, headers=headers) as resp:
        data = await resp.read()
        headers = dict(resp.headers)

        if raw:
            return data, resp.status, headers

        for h in ["Transfer-Encoding", "Content-Encoding", "Server", "Date"]:
            headers.pop(h, None)
        return data, resp.status, headers


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
    if ".." in path or path.startswith("/") or Path(path).is_absolute():
        return Response(status_code=400, content="Bad Request")

    file_path = (RESOURCE_DIR / path).resolve()

    if not file_path.is_relative_to(RESOURCE_DIR.resolve()):
        return Response(status_code=400, content="Bad Request")

    if not file_path.exists() or not file_path.is_file():
        return Response(status_code=404, content="Not Found")

    return FileResponse(file_path)
