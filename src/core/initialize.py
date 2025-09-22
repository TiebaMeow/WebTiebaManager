from src.db import Database
from src.tieba.crawler import Crawler
from src.user.manager import UserManager
from src.utils.anonymous import stop_anonymous_clients
from src.utils.cache import CacheCleaner

from .controller import Controller


def initialize():
    if Controller.initialize():
        Controller.Start.on(UserManager.load_users)
        Controller.Start.on(Database.startup)
        Controller.Start.on(CacheCleaner.start)
        Controller.SystemConfigChange.on(Crawler.restart)
        Controller.SystemConfigChange.on(Database.update_config)
        Controller.SystemConfigChange.on(CacheCleaner.update_clear_cache_time)
        Controller.Stop.on(UserManager.clear_users)
        Controller.Stop.on(Database.teardown)
        Controller.Stop.on(Crawler.start_or_stop)
        Controller.Stop.on(CacheCleaner.stop)
        Controller.Stop.on(stop_anonymous_clients)
        UserManager.UserChange.on(Crawler.update_needs)
        UserManager.UserConfigChange.on(Crawler.update_needs)
