from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.core.config import ServerConfig
from src.core.constants import DEV, MAIN_SERVER, PUBLIC, SYSTEM_CONFIG_PATH
from src.core.controller import Controller
from src.core.initialize import initialize
from src.user.manager import UserManager
from src.utils.logging import exception_logger, system_logger
from src.utils.tools import random_str

HTTP_ALLOW_ORIGINS = ["*" if DEV else MAIN_SERVER]


def initialize_server_config():
    if PUBLIC:
        system_logger.warning("正在以公网模式运行，请尽快完成初始化")
        return ServerConfig(host="0.0.0.0")
    else:
        return ServerConfig()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # why initialize here?
    # if __name__ == "__main__": 中的initialize()不会在uvicorn 每次reload时调用
    # 在此调用以保证所有模式下都能正确初始化
    initialize()

    await Controller.start()
    if Server.need_initialize():
        system_logger.warning(f"初始化密钥: {Server.secure_key()}")

    yield
    await Controller.stop()
    Server._secure_key = None


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
    _secure_key: str | None = None

    @classmethod
    def secure_key(cls):
        if cls._secure_key is None:
            cls._secure_key = random_str(8)
        return cls._secure_key

    @classmethod
    def need_system(cls):
        return not SYSTEM_CONFIG_PATH.exists()

    @classmethod
    def need_user(cls):
        return not bool(UserManager.get_valid_usernames())

    @classmethod
    def need_initialize(cls):
        return cls.need_system() or cls.need_user()

    @classmethod
    def console_prompt(cls, config: ServerConfig, log_fn=system_logger.info):
        listenable_urls = config.listenable_urls
        if len(listenable_urls) == 1:
            log_fn(f"访问 {listenable_urls[0]} 进行管理")
        else:
            log_fn("访问以下地址进行管理:")
            for url in listenable_urls:
                log_fn(f"- {url}")

    @classmethod
    async def serve(cls):
        while True:
            # TODO 当需要初始化配置时，如果端口被占用，则+1

            config = initialize_server_config() if cls.need_system() else Controller.config.server

            server = uvicorn.Server(uvicorn.Config(app, **config.uvicorn_config_param))
            cls.server = server

            if cls.need_initialize():
                system_logger.warning("系统未初始化，请先进行初始化")
                cls.console_prompt(config, log_fn=system_logger.warning)
            else:
                system_logger.info("正在启动服务")
                cls.console_prompt(config)

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
            "src.api.server:app", host=config.host, port=config.port, log_level="info", access_log=True, reload=True
        )

    @classmethod
    def run(cls):
        try:
            with exception_logger("服务运行异常", reraise=True):
                if DEV:
                    config = initialize_server_config() if cls.need_system() else Controller.config.server
                    system_logger.warning("开发模式运行，请勿在生产环境使用")
                    cls.console_prompt(config, log_fn=system_logger.warning)
                    cls.dev_run(config)
                else:
                    import asyncio

                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(cls.serve())
        except KeyboardInterrupt:
            system_logger.info("服务已停止")
