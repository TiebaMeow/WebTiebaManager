import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.config import CONFIG_PATH
from core.control import Controller
from core.user.manager import UserManager

HTTP_ALLOW_ORIGINS = ["*"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await Controller.start()
    yield
    await Controller.stop()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=HTTP_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


class BaseResponse[T](BaseModel):
    code: int
    data: T


class Server:
    need_restart: bool = False
    server: uvicorn.Server | None = None

    @classmethod
    async def need_system(cls):
        return not CONFIG_PATH.exists()

    @classmethod
    async def need_user(cls):
        await UserManager.silent_load_users()
        return not UserManager.users

    @classmethod
    async def need_initialize(cls):
        return await cls.need_system() or await cls.need_user()

    @classmethod
    async def serve(cls):
        while True:
            # TODO 当需要初始化配置时，如果端口被占用，则+1
            server = uvicorn.Server(
                uvicorn.Config(app, host="0.0.0.0", port=36799, log_level="error", access_log=False)
                if await cls.need_system()
                else uvicorn.Config(
                    app,
                    host=Controller.config.server.host,
                    port=Controller.config.server.port,
                    log_level=Controller.config.server.log_level,
                    access_log=Controller.config.server.access_log,
                )
            )
            cls.server = server

            if await cls.need_initialize():
                print("server start at http://0.0.0.0:36799")
            else:
                print(f"server start at {Controller.config.server.url}")

            await server.serve()

            if not cls.need_restart:
                break

    @classmethod
    async def shutdown(cls):
        if cls.server:
            cls.server.should_exit = True

    @classmethod
    def dev_run(cls):
        uvicorn.run(
            "core.server.server:app", host="0.0.0.0", port=36799, log_level="info", access_log=True, reload=True
        )

    @classmethod
    def run(cls):
        if "--dev" in sys.argv:
            print("run server in dev mode")
            cls.dev_run()
        else:
            import asyncio

            loop = asyncio.get_event_loop()
            loop.run_until_complete(cls.serve())
