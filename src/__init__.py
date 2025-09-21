import src.http  # 确保顶级包被加载  # noqa: I001

from src.control import Controller

Controller.initialize()  # 预加载配置
