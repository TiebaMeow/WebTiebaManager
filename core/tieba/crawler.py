from __future__ import annotations

import asyncio

import aiotieba
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from core.constance import BASE_DIR, PID_CACHE_EXPIRE
from core.control import Controller
from core.db.interface import ContentModel, Database
from core.typedef import Comment, Post, Thread
from core.user.manager import UserManager
from core.util.cache import ClearCache, ExpireCache
from core.util.tools import EtaSleep

from .browser import TiebaBrowser


@ClearCache.on
async def clear_content_cache(_=None):
    need_clear: list[int] = [
        content.pid async for content in Database.iter_all_contents() if await Spider.cache.get(content.pid) is None
    ]
    await Database.delete_contents_by_pids(need_clear)


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
            if cache_thread_mark is None and thread.reply_num > 0:
                yield Thread.from_aiotieba_data(thread)
            elif thread_mark != cache_thread_mark:
                updated = True

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
                if reply_num_cache is None and reply_num > 4 and need.post:
                    yield post
                elif reply_num != reply_num_cache:
                    updated = True

                if not updated or not need.post:
                    await self.cache.set(post.pid, reply_num)
                    continue

                target_pn = (reply_num + 29) // 30
                async with self.eta:
                    comments = await self.client.get_comments(post.tid, post.pid, pn=target_pn)
                    raw_comments.extend(Comment.from_aiotieba_data(i, title=thread.title) for i in comments)

                await self.cache.set(post.pid, reply_num)

                for comment in raw_comments:
                    if await self.cache.get(comment.pid) is None:
                        yield comment
                    await self.cache.set(comment.pid, 1)


class Crawler:
    spider = Spider()
    needs: dict[str, CrawlNeed] = {}
    task: asyncio.Task | None = None

    @classmethod
    async def update_needs(cls, _=None):
        new_needs = {}
        for user in UserManager.users.values():
            forum = user.config.forum
            if user.enable and forum and user.config.rule_sets and forum.fname:
                need = CrawlNeed(thread=forum.thread, post=forum.post, comment=forum.comment)
                new_needs[forum.fname] = new_needs.get(forum.fname, CrawlNeed()) + need
        cls.needs = new_needs
        await cls.start_or_stop()

    @classmethod
    async def start_or_stop(cls, _: None = None):
        if cls.needs and not cls.task and Controller.running:
            cls.task = asyncio.create_task(cls.crawl())
        elif (not cls.needs or not Controller.running) and cls.task:
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
            try:
                for forum, need in cls.needs.items():
                    async for content in cls.spider.crawl(forum, need):
                        try:
                            await Database.save_items([ContentModel.from_content(content)])
                        except IntegrityError:
                            pass

                        await Controller.DispatchContent.broadcast(content)
            except Exception:
                from traceback import format_exc

                print(format_exc())
            await asyncio.sleep(Controller.config.scan.loop_cd)

    @classmethod
    async def start(cls):
        await cls.spider.init_client()


UserManager.UserChange.on(Crawler.update_needs)
UserManager.UserConfigChange.on(Crawler.update_needs)
Controller.SystemConfigChange.on(Crawler.restart)
Controller.Stop.on(Crawler.start_or_stop)
