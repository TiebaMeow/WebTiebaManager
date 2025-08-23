"""
配置获取方法

from core.control import Controller
config = Controller.config

异步初始化/结束方法

Controller.Start.on(async_start_function) < 在开始服务前调用
Controller.Stop.on(async_stop_function) < 结束服务后调用

最终需要呈现的效果

from core.db import DBConn (db可以为文件夹)

async with DBConn() as c:
    result = await c.execute("xxx",(a,b,c))

NOTE
需求大概是这样，如果有更好的idea也可以
"""

# 配置格式
# 会有以下两种格式的配置传入

from pydantic import BaseModel


class SqliteConfig(BaseModel):
    path: str
    username: str
    password: str


class PostgresqlConfig(BaseModel):
    host: str
    port: int
    username: str
    password: str
    db: str


DatabaseConfig = SqliteConfig | PostgresqlConfig

# 调用方法
# DBConn实际上可以为函数，返回SqliteDBConn/PostgresqlDBConn等
# 建议使用连接池*

class DBConn(object):
    def __init__(self): ...

    # 一系列封装的方法, 可以拓展共同项
    async def execute(self, sql, params=None): ...

    async def fetch_one(self, sql, params=None): ...

    async def fetch_all(self, sql, params=None): ...
