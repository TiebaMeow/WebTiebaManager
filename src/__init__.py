import src.http  # 确保顶级包被加载  # noqa: I001

from src.control import Controller
from src.tieba import Crawler  # 确保Crawler被加载

Controller.initialize()  # 预加载配置
