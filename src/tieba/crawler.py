from __future__ import annotations

import asyncio

import aiotieba
from pydantic import BaseModel

from src.constance import BASE_DIR, PID_CACHE_EXPIRE
from src.control import Controller
from src.db.interface import ContentModel, Database
from src.typedef import Comment, Post, Thread
from src.user.manager import UserManager
from src.util.cache import ClearCache, ExpireCache
from src.util.logging import exception_logger, system_logger
from src.util.tools import EtaSleep, Timer

from .browser import TiebaBrowser


@ClearCache.on
async def clear_content_cache(_=None):
    with Timer() as t:
        db_pids = await Database.get_all_pids()
        cache_pids = {int(i) for i in await Spider.cache.keys()}
        need_clear: set[int] = db_pids - cache_pids
        if need_clear:
            await Database.delete_contents_by_pids(need_clear)
            system_logger.info(f"清理内容缓存，清理 {len(need_clear)} 条内容，耗时 {t.cost:.2f} 秒")
        else:
            system_logger.info(f"清理内容缓存，无需清理，耗时 {t.cost:.2f} 秒")


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
    CACHE_DIR = BASE_DIR / "crawler_cache"
    cache: ExpireCache[int | str] = ExpireCache(directory=CACHE_DIR, expire_time=PID_CACHE_EXPIRE)

    client: aiotieba.Client
    browser: TiebaBrowser
    eta: EtaSleep

    class InvalidContentError(Exception):
        pass

    def __init__(self):
        self.update_config(None)
        Controller.SystemConfigChange.on(self.update_config)
        self.client = None  # type: ignore
        self.browser = None  # type: ignore

    def update_config(self, _: None):
        self.eta = EtaSleep(Controller.config.scan.query_cd)

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
        for i in range(1, scan.thread_page_forward + 1):
            async with self.eta:
                raw_threads.extend(await self.client.get_threads(forum, pn=i))

        for thread in raw_threads:
            thread_mark = f"{thread.last_time}.{thread.reply_num}"
            cache_thread_mark = await self.cache.get(thread.pid)
            updated = (cache_thread_mark is None and thread.reply_num > 0) or (thread_mark != cache_thread_mark)

            if cache_thread_mark is None and need.thread:
                yield Thread.from_aiotieba_data(thread)

            if not updated or (not need.post and not need.comment):
                await self.cache.set(thread.pid, thread_mark)
                continue

            raw_posts: list[Post] = []
            raw_comments: list[Comment] = []
            reply_num_dict: dict[int, int] = {}

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
                        reply_num_dict.update(data.reply_num)

            await self.cache.set(thread.pid, thread_mark)

            for post in raw_posts:
                if post.floor == 1:
                    continue
                reply_num = reply_num_dict.get(post.pid, 0)
                reply_num_cache = await self.cache.get(post.pid)

                updated = (reply_num_cache is None and reply_num > 4) or (reply_num != reply_num_cache)

                if reply_num_cache is None and need.post:
                    yield post

                if not updated or not need.post:
                    await self.cache.set(post.pid, reply_num)
                    continue

                target_pn = (reply_num + 29) // 30
                async with self.eta:
                    comments = await self.client.get_comments(post.tid, post.pid, pn=target_pn)
                    raw_comments.extend(Comment.from_aiotieba_data(i, title=thread.title) for i in comments)

                await self.cache.set(post.pid, reply_num)

                for comment in raw_comments:
                    if await self.cache.get(comment.pid) is None and need.comment:
                        yield comment
                    await self.cache.set(comment.pid, 1)


class Crawler:
    spider = Spider()
    needs: dict[str, CrawlNeed] = {}
    task: asyncio.Task | None = None

    @classmethod
    async def update_needs(cls, _=None):
        new_needs: dict[str, CrawlNeed] = {}
        for user in UserManager.users.values():
            forum = user.config.forum
            if user.enable and forum and user.config.rule_sets and forum.fname:
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
                    system_logger.info(f"更新爬虫监控需求：{change_str[0]}")
                elif change_str:
                    system_logger.info(f"更新爬虫监控需求：\n{'\n'.join(change_str)}")

                system_logger.debug(
                    "当前爬虫监控需求：\n" + "\n".join(f"{fname}{need}" for fname, need in new_needs.items())
                )

            cls.needs = new_needs
            await cls.start_or_stop()

    @classmethod
    async def start_or_stop(cls, _: None = None):
        if cls.needs and not cls.task and Controller.running:
            system_logger.info(f"启动爬虫，监控 {len(cls.needs)} 个贴吧")
            cls.task = asyncio.create_task(cls.crawl())
        elif (not cls.needs or not Controller.running) and cls.task:
            if not Controller.running:
                system_logger.info("停止爬虫")
            elif not cls.needs:
                system_logger.info("停止爬虫，没有需要监控的贴吧")
            cls.task.cancel()
            cls.task = None

    @classmethod
    async def restart(cls, _: None = None):
        if cls.task:
            cls.task.cancel()
            cls.task = asyncio.create_task(cls.crawl())

    @classmethod
    async def crawl(cls):
        while True:
            with exception_logger("爬虫循环异常"):
                for forum, need in cls.needs.items():
                    async for content in cls.spider.crawl(forum, need):
                        system_logger.debug(f"爬取到新内容 {content.mark} 来自 {forum}")
                        await Database.save_items([ContentModel.from_content(content)])
                        await Controller.DispatchContent.broadcast(content)
            await asyncio.sleep(Controller.config.scan.loop_cd)

    @classmethod
    async def start(cls):
        await cls.spider.init_client()


UserManager.UserChange.on(Crawler.update_needs)
UserManager.UserConfigChange.on(Crawler.update_needs)
Controller.SystemConfigChange.on(Crawler.restart)
Controller.Stop.on(Crawler.start_or_stop)
