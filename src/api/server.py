import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.core.config import ServerConfig
from src.core.constants import (
    ALLOW_ORIGINS,
    DEV,
    DEV_WEBUI,
    IS_EXE,
    PROGRAM_VERSION,
    PUBLIC,
    SYSTEM_CONFIG_PATH,
    WEB_UI_CODE,
)
from src.core.controller import Controller
from src.core.initialize import initialize
from src.user.manager import UserManager
from src.utils.logging import exception_logger, get_uvicorn_log_config, system_logger
from src.utils.tools import random_str


def get_log_config():
    return get_uvicorn_log_config("uvicorn")


def initialize_server_config():
    if PUBLIC:
        return ServerConfig(host="0.0.0.0")
    else:
        return ServerConfig()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # why initialize here?
    # if __name__ == "__main__": 中的initialize()不会在uvicorn 每次reload时调用
    # 在此调用以保证所有模式下都能正确初始化
    initialize()

    # if DEV:
    config = initialize_server_config() if Server.need_system() else Controller.config.server
    Server.display_startup_messages(config)

    await Controller.start()

    yield
    await Controller.stop()
    Server._secure_key = None


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
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
    system_logger.exception(f"服务器捕获到未经处理的异常. {exc}")
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
    def should_exit(cls):
        if cls.server is None:
            return not DEV
        return cls.server.should_exit

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
    def display_startup_messages(cls, config: ServerConfig):
        system_logger.info(f"WebTiebaManager v{PROGRAM_VERSION}[{WEB_UI_CODE}]")
        if IS_EXE:
            system_logger.info("EXE 运行环境：如遇异常或启动失败，建议使用 Python 环境部署")
        if DEV:
            system_logger.warning("开发模式已启用，请勿在生产环境使用")
        if DEV_WEBUI:
            system_logger.warning("网页开发模式已启用，请勿在生产环境使用")

        if cls.need_initialize():
            system_logger.warning(f"初始化密钥: {cls.secure_key()}")
            system_logger.warning("检测到程序未初始化，请完成初始化")
            if PUBLIC:
                # TODO 公网运行模式下，添加一定时间不初始化则自动关闭服务的功能
                system_logger.warning("正在以公网模式运行，请尽快完成初始化！")

        listenable_urls = config.listenable_urls
        log_fn = system_logger.warning if DEV else system_logger.info
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
            server = uvicorn.Server(uvicorn.Config(app, **config.uvicorn_config_param, log_config=get_log_config()))
            cls.server = server
            # cls.display_startup_messages(config)

            await server.serve()

            if not cls.need_restart:
                break

    @classmethod
    async def shutdown_task(cls, restart: bool = False, shutdown_timeout: int = 10):
        """
        创建后台任务优雅关闭服务器
        """
        return asyncio.create_task(cls.shutdown(restart=restart, shutdown_timeout=shutdown_timeout))

    @classmethod
    async def shutdown(cls, restart: bool = False, shutdown_timeout: int = 10):
        """
        优雅关闭服务器，如果超时则强制退出

        WARNING: 不应在http请求中直接调用此函数，应使用 shutdown_task，创建后台任务调用，否则会导致uvicorn无法优雅关闭

        Args:
            shutdown_timeout: 等待时间（秒），默认10秒
        """
        if cls.server is None:
            if DEV:
                if restart:
                    system_logger.warning("开发模式下无法自动关闭服务，请手动停止后重启")
                else:
                    system_logger.warning("开发模式下无法自动关闭服务，请手动停止")
            else:
                system_logger.warning("服务器未运行，无法关闭")
            return

        if restart:
            system_logger.info("正在重启服务...")
        else:
            system_logger.info("正在关闭服务...")

        cls.need_restart = restart

        server = cls.server

        server.should_exit = True

        waited = 0
        poll_interval = 0.1

        while waited < shutdown_timeout:
            # 检查服务器是否仍在运行（通过检查连接状态）
            if not server.server_state.connections and not server.server_state.tasks:
                break

            await asyncio.sleep(poll_interval)
            waited += poll_interval
        else:
            server.force_exit = True

            system_logger.warning("等待超时，正在强制退出...")
            system_logger.warning("若程序未能退出，请手动结束进程")

    @classmethod
    def dev_run(cls, config: ServerConfig):
        uvicorn.run(
            "src.api.server:app",
            host=config.host,
            port=config.port,
            log_level="info",
            access_log=True,
            reload=True,
            log_config=get_log_config(),
        )

    @classmethod
    def run(cls):
        try:
            with exception_logger("服务运行异常", reraise=True):
                if DEV:
                    config = initialize_server_config() if cls.need_system() else Controller.config.server
                    cls.dev_run(config)
                else:
                    import asyncio

                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(cls.serve())
        except KeyboardInterrupt:
            system_logger.info("服务已停止")
