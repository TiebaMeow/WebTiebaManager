from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import aiotieba
from pydantic import BaseModel

from src.core.constants import PID_CACHE_EXPIRE
from src.core.controller import Controller
from src.db import Database, UpdateStatus
from src.models import ContentModel, UserLevelModel, UserModel
from src.schemas.tieba import Comment, Post, Thread
from src.user.manager import UserManager
from src.utils.cache import ClearCache
from src.utils.logging import exception_logger, system_logger
from src.utils.tools import EtaSleep, Timer

from .browser import TiebaBrowser

if TYPE_CHECKING:
    from src.core.config import SystemConfig
    from src.schemas.event import UpdateEventData


@ClearCache.on
async def clear_content_cache(_=None):
    with Timer() as t:
        clear_before = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(seconds=PID_CACHE_EXPIRE)
        clear_num = await Database.clear_contents_before(clear_before)
        if clear_num:
            system_logger.info(f"成功清理 {clear_num} 条过期内容缓存. 耗时: {t.cost:.2f}s")
        else:
            system_logger.debug(f"无需清理内容缓存. 耗时: {t.cost:.2f}s")


class CrawlNeed(BaseModel):
    thread: bool = True
    post: bool = True
    comment: bool = True

    def __add__(self, other: CrawlNeed):
        return CrawlNeed(
            thread=self.thread or other.thread,
            post=self.post or other.post,
            comment=self.comment or other.comment,
        )

    def __sub__(self, other: CrawlNeed):
        """
        c1 - c2: c1将c2为True的内容设置为False
        """
        return CrawlNeed(
            thread=self.thread and not other.thread,
            post=self.post and not other.post,
            comment=self.comment and not other.comment,
        )

    def __str__(self) -> str:
        # return f"[{'T' if self.thread else '-'}{'P' if self.post else '-'}{'C' if self.comment else '-'}]"
        return (
            "["
            + "/".join(
                i
                for i in (
                    "主题贴" if self.thread else "",
                    "回帖" if self.post else "",
                    "楼中楼" if self.comment else "",
                )
                if i
            )
            + "]"
        )

    @classmethod
    def empty(cls):
        return cls(thread=False, post=False, comment=False)

    @property
    def is_empty(self):
        return not (self.thread or self.post or self.comment)


class Spider:
    client: aiotieba.Client
    browser: TiebaBrowser
    eta: EtaSleep

    class InvalidContentError(Exception):
        pass

    def __init__(self):
        Controller.SystemConfigChange.on(self.update_config)
        self.client = None  # type: ignore
        self.browser = None  # type: ignore
        self.eta = EtaSleep(Controller.config.scan.query_cd)

    def update_config(self, data: UpdateEventData[SystemConfig]):
        if data.old.scan.query_cd != data.new.scan.query_cd:
            self.eta = EtaSleep(data.new.scan.query_cd)

    async def init_client(self):
        if self.client is None:
            self.client = aiotieba.Client()
            await self.client.__aenter__()
        if self.browser is None:
            self.browser = TiebaBrowser()
            await self.browser.__aenter__()

    async def stop_client(self):
        if self.client is not None:
            await self.client.__aexit__()
            self.client = None  # type: ignore
        if self.browser is not None:
            await self.browser.__aexit__()
            self.browser = None  # type: ignore

    async def crawl(self, forum: str, need: CrawlNeed | None = None):
        if need is None:
            need = CrawlNeed()
        await self.init_client()
        scan = Controller.config.scan
        raw_threads: list[aiotieba.typing.Thread] = []
        # 获取主题列表
        with Timer() as t:
            for i in range(1, scan.thread_page_forward + 1):
                async with self.eta:
                    raw_threads.extend(await self.client.get_threads(forum, pn=i))
        system_logger.debug(f"[perf] 爬取贴吧 {forum} 的 {len(raw_threads)} 个主题帖耗时: {t.cost:.2f}s")

        for thread in raw_threads:
            with Timer() as t_thread:
                updated = await Database.check_and_update_cache(thread)

                # NEW or NEW_WITH_CHILD
                if updated & UpdateStatus.IS_NEW and need.thread:
                    yield Thread.from_aiotieba_data(thread)

                # UNCHANGED or NEW
                if updated & UpdateStatus.IS_STABLE or (not need.post and not need.comment):
                    continue

                # UPDATED or NEW_WITH_CHILD

                raw_posts: list[Post] = []
                raw_comments: list[Comment] = []

                with Timer() as t_posts:
                    async with self.eta:
                        data = await self.browser.get_posts(thread.tid, pn=1)

                        total_page = data.total_page
                        # 优化页码遍历逻辑
                        pages = list(range(2, min(scan.post_page_forward + 1, total_page + 1)))
                        if total_page < scan.post_page_forward + scan.post_page_backward:
                            pages += list(range(len(pages) + 2, total_page + 1))
                        else:
                            pages += list(
                                range(total_page, max(total_page - scan.post_page_backward, scan.post_page_forward), -1)
                            )

                        for i in pages:
                            async with self.eta:
                                data = await self.browser.get_posts(thread.tid, pn=i)
                                raw_posts.extend(data.posts)
                                raw_comments.extend(data.comments)
                system_logger.debug(
                    f"[perf] 爬取主题帖 {thread.tid} 的 {len(raw_posts)} 个回帖和 {len(raw_comments)} 个楼中楼耗时: {t_posts.cost:.2f}s"
                )

                for post in raw_posts:
                    if post.floor == 1:
                        continue
                    updated = await Database.check_and_update_cache(post)

                    if updated & UpdateStatus.IS_NEW and need.post:
                        yield post

                    if updated & UpdateStatus.IS_STABLE or not need.post:
                        continue

                    target_pn = (post.reply_num + 29) // 30
                    with Timer() as t_comments:
                        async with self.eta:
                            comments = await self.client.get_comments(post.tid, post.pid, pn=target_pn)
                            raw_comments.extend(Comment.from_aiotieba_data(i, title=thread.title) for i in comments)
                    system_logger.debug(
                        f"[perf] 爬取回帖 {post.pid} 的 {len(comments)} 个楼中楼耗时: {t_comments.cost:.2f}s"
                    )

                    for comment in raw_comments:
                        updated = await Database.check_and_update_cache(comment)
                        if updated & UpdateStatus.IS_NEW and need.comment:
                            yield comment
            system_logger.debug(f"[perf] 处理主题帖 {thread.tid} 耗时: {t_thread.cost:.2f}s")


class Crawler:
    spider: Spider | None = None
    needs: dict[str, CrawlNeed] = {}
    task: asyncio.Task | None = None

    @classmethod
    async def update_needs(cls, _=None):
        new_needs: dict[str, CrawlNeed] = {}
        for user in UserManager.users.values():
            forum = user.config.forum
            if user.enable and forum and user.config.rules and forum.fname:
                need = CrawlNeed(thread=forum.thread, post=forum.post, comment=forum.comment)
                new_needs[forum.fname] = new_needs.get(forum.fname, CrawlNeed.empty()) + need

        for fname, need in new_needs.copy().items():
            if need.is_empty:
                del new_needs[fname]

        if cls.needs != new_needs:
            need_add: dict[str, CrawlNeed] = {}
            need_remove: dict[str, CrawlNeed] = {}

            for fname, new_need in new_needs.items():
                if fname not in cls.needs:
                    need_add[fname] = new_need
                elif new_need != cls.needs[fname]:
                    old_need = cls.needs[fname]
                    need_remove[fname] = old_need - new_need
                    need_add[fname] = new_need - old_need

            need_remove.update({fname: old_need for fname, old_need in cls.needs.items() if fname not in new_needs})

            change_str = []

            for fname in set(need_remove) | set(need_add):
                if fname in need_add and not need_add[fname].is_empty:
                    change_str.append(f"+ {fname}{need_add[fname]}")
                if fname in need_remove and not need_remove[fname].is_empty:
                    change_str.append(f"- {fname}{need_remove[fname]}")

            if Controller.running:
                if len(change_str) == 1:
                    system_logger.info(f"爬虫监控需求已更新: {change_str[0]}")
                elif change_str:
                    system_logger.info(f"爬虫监控需求已更新:\n{'\n'.join(change_str)}")

                system_logger.debug(
                    "当前爬虫监控需求:\n" + "\n".join(f"{fname}{need}" for fname, need in new_needs.items())
                )

            cls.needs = new_needs
            await cls.start_or_stop()

    @classmethod
    async def start_or_stop(cls, _: None = None):
        if cls.needs and not cls.task and Controller.running:
            cls.task = asyncio.create_task(cls.crawl())
            system_logger.info(f"爬虫已启动，监控 {len(cls.needs)} 个贴吧")
        elif (not cls.needs or not Controller.running) and cls.task:
            cls.task.cancel()
            cls.task = None

            if not Controller.running:
                system_logger.info("爬虫已停止")
            elif not cls.needs:
                system_logger.info("没有需要监控的贴吧，爬虫已停止")

    @classmethod
    async def restart(cls, data: UpdateEventData[SystemConfig]):
        if cls.task and data.old.scan != data.new.scan:
            cls.task.cancel()
            cls.task = asyncio.create_task(cls.crawl())

    @classmethod
    async def crawl(cls):
        while True:
            users: dict[int, UserModel] = {}
            user_levels: dict[str, UserLevelModel] = {}  # user_id:fname -> UserLevelModel
            contents: list[ContentModel] = []

            with exception_logger("爬虫任务发生异常"), Timer() as t:
                for forum, need in cls.needs.items():
                    async for content in cls.get_spider().crawl(forum, need):
                        system_logger.debug(f"爬取到新内容. {content.mark} 来自 {forum}")

                        if content.user.user_id not in users:
                            users[content.user.user_id] = UserModel.from_user(content.user)
                        level_identifier = f"{content.user.user_id}:{forum}"
                        if level_identifier not in user_levels:
                            user_levels[level_identifier] = UserLevelModel(
                                user_id=content.user.user_id,
                                fname=forum,
                                level=content.user.level,
                            )
                        contents.append(ContentModel.from_content(content))
                        await Controller.DispatchContent.broadcast(content)

            system_logger.debug(f"[perf] 爬虫任务完成，共爬取 {len(contents)} 条内容，耗时: {t.cost:.2f}s")

            with exception_logger("爬虫用户数据保存发生异常"), Timer() as t:
                # TODO 理论上存在处理过程中的user model获取请求 (ProcessLog模块)，目前就先这样把 <
                await Database.save_items(users.values())
                await Database.save_items(user_levels.values())
                await Database.save_items(contents)

            system_logger.debug(
                f"[perf] 保存 {len(users)} 个用户、{len(user_levels)} 个用户等级、{len(contents)} 条内容耗时: {t.cost:.2f}s"
            )

            await asyncio.sleep(Controller.config.scan.loop_cd)

    @classmethod
    def get_spider(cls) -> Spider:
        if not cls.spider:
            cls.spider = Spider()
        return cls.spider

    @classmethod
    async def start(cls):
        await cls.get_spider().init_client()
