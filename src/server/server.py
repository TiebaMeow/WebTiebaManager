from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.constance import DEV, MAIN_SERVER, SYSTEM_CONFIG_PATH
from src.control import Controller
from src.tieba import crawler
from src.user.manager import UserManager
from src.util.logging import exception_logger, system_logger

from .config import ServerConfig

HTTP_ALLOW_ORIGINS = ["*" if DEV else MAIN_SERVER]


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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"message": exc.detail},
        )
    system_logger.exception(f"服务器内部错误: {exc}")
    return JSONResponse(
        status_code=500,
        content={"message": "服务器内部错误", "detail": str(exc)},
    )


class BaseResponse[T](BaseModel):
    code: int = 200
    message: str | None = None
    data: T


class Server:
    need_restart: bool = False
    server: uvicorn.Server | None = None
    _need_initialize: bool | None = None

    @classmethod
    def need_system(cls):
        return not SYSTEM_CONFIG_PATH.exists()

    @classmethod
    async def need_user(cls):
        # TODO 优化为无需async的检测
        await UserManager.silent_load_users()
        return not UserManager.users

    @classmethod
    async def need_initialize(cls):
        if cls._need_initialize is None:
            cls._need_initialize = cls.need_system() or await cls.need_user()

        return cls._need_initialize

    @classmethod
    async def serve(cls):
        while True:
            # TODO 当需要初始化配置时，如果端口被占用，则+1

            config = ServerConfig() if cls.need_system() else Controller.config.server

            server = uvicorn.Server(uvicorn.Config(app, **config.uvicorn_config_param))
            cls.server = server

            if await cls.need_initialize():
                system_logger.warning("系统未初始化，请先进行初始化")
                system_logger.warning(f"访问 {config.url} 进行初始化")
            else:
                system_logger.info("正在启动服务")
                system_logger.info(f"访问 {config.url} 进行管理")

            await server.serve()

            if not cls.need_restart:
                break

    @classmethod
    async def shutdown(cls):
        if cls.server:
            cls.server.should_exit = True

    @classmethod
    def dev_run(cls, config: ServerConfig):
        uvicorn.run(
            "src.server.server:app", host=config.host, port=config.port, log_level="info", access_log=True, reload=True
        )

    @classmethod
    def run(cls):
        try:
            with exception_logger("服务运行异常", reraise=True):
                if DEV:
                    config = ServerConfig() if cls.need_system() else Controller.config.server
                    system_logger.warning("开发模式运行，请勿在生产环境使用")
                    system_logger.warning(f"访问 {config.url} 进行管理")
                    cls.dev_run(config)
                else:
                    import asyncio

                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(cls.serve())
        except KeyboardInterrupt:
            system_logger.info("服务已停止")
