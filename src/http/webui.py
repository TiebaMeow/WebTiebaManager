import aiohttp
from fastapi import Request, Response
from pydantic import BaseModel

from src.constance import MAIN_SERVER, PROGRAM_VERSION, WEB_UI_VERSION
from src.control import Controller
from src.server import Server, app

WEBUI_BASE = MAIN_SERVER + f"/webui/{WEB_UI_VERSION}"


class Proxy:
    _client: aiohttp.ClientSession | None = None

    @classmethod
    async def get_client(cls) -> aiohttp.ClientSession:
        if cls._client is None or cls._client.closed:
            cls._client = aiohttp.ClientSession()
            await cls._client.__aenter__()
        return cls._client

    @classmethod
    async def stop(cls, _=None):
        if cls._client and not cls._client.closed:
            await cls._client.__aexit__(None, None, None)
            cls._client = None

    @classmethod
    async def get(cls, url: str, request: Request, raw=False):
        client = await cls.get_client()
        headers = {key: value for key, value in request.headers.items() if key != "host"}
        async with client.get(url, headers=headers) as resp:
            data = await resp.read()
            headers = dict(resp.headers)

            if raw:
                return data, resp.status, headers

            for h in ["Transfer-Encoding", "Content-Encoding", "Server", "Date"]:
                headers.pop(h, None)
            return data, resp.status, headers


Controller.Stop.on(Proxy.stop)


@app.get("/", tags=["webui"])
async def index(request: Request):
    content, status_code, headers = await Proxy.get(f"{WEBUI_BASE}/index.html", request)
    return Response(content=content, status_code=status_code, headers=headers)


@app.get("/assets/{path:path}", tags=["webui"])
async def assets(path: str, request: Request):
    content, status_code, headers = await Proxy.get(f"{WEBUI_BASE}/assets/{path}", request)
    return Response(content=content, status_code=status_code, headers=headers)


class ServerInfo(BaseModel):
    version: str
    need_initialize: bool


@app.get("/api/info", tags=["webui"])
async def webui_info() -> ServerInfo:
    return ServerInfo(version=PROGRAM_VERSION, need_initialize=await Server.need_initialize())
