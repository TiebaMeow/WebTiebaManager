import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import CONFIG_PATH
from core.constance import USER_DIR
from core.control import Controller

HTTP_ALLOW_ORIGINS = ["*"]


app = FastAPI()


class Server:
    need_restart: bool = False
    server: uvicorn.Server | None = None

    @classmethod
    def need_system(cls):
        return not CONFIG_PATH.exists()

    @classmethod
    def need_user(cls):
        return not bool([i for i in USER_DIR.iterdir() if i.is_dir()])

    @classmethod
    def need_initialize(cls):
        return cls.need_system() or cls.need_user()

    @classmethod
    async def serve(cls):
        app.add_middleware(
            CORSMiddleware,
            allow_origins=HTTP_ALLOW_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        )
        while True:
            # TODO 当需要初始化配置时，如果端口被占用，则+1
            server = uvicorn.Server(
                uvicorn.Config(app, host="0.0.0.0", port=36799, log_level="error", access_log=False)
                if cls.need_system()
                else uvicorn.Config(
                    app,
                    host=Controller.config.server.host,
                    port=Controller.config.server.port,
                    log_level=Controller.config.server.log_level,
                    access_log=Controller.config.server.access_log,
                )
            )
            cls.server = server
            if cls.need_initialize():
                print("server start at http://0.0.0.0:36799")
            else:
                await Controller.start()
                print(f"server start at {Controller.config.server.url}")

            await server.serve()

            if not cls.need_restart:
                break

    @classmethod
    async def shutdown(cls):
        if cls.server:
            cls.server.should_exit = True
