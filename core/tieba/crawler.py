import asyncio

import aiotieba
from pydantic import BaseModel

from core.util.cache import ExpireCache
from core.constance import BASE_DIR, PID_CACHE_EXPIRE
from core.util.tools import EtaSleep
from .browser import TiebaBrowser
from core.typedef import Thread, Post, Comment
from core.control import Controller
from core.user.manager import UserManager


class CrawlNeed(BaseModel):
    thread: bool = True
    post: bool = True
    comment: bool = True

    def __add__(self, other: "CrawlNeed"):
        return CrawlNeed(
            thread=self.thread or other.thread,
            post=self.post or other.post,
            comment=self.comment or other.comment,
        )


class Crawler:
    CACHE_FILE = BASE_DIR / "pid_cache.json"
    cache: ExpireCache[int | str] = ExpireCache(
        expire=PID_CACHE_EXPIRE, path=CACHE_FILE
    )
    cache.load_data()

    client: aiotieba.Client
    browser: TiebaBrowser
    eta: EtaSleep

    class InvalidContent(Exception):
        pass

    def __init__(self):
        self.update_config(None)
        Controller.MainConfigChange.on(self.update_config)

    def update_config(self, _: None):
        self.eta = EtaSleep(Controller.config.scan.query_cd)

    async def init_client(self):
        if not self.client:
            self.client = aiotieba.Client()
            await self.client.__aenter__()

        if not self.browser:
            self.browser = TiebaBrowser()
            await self.browser.__aenter__()

    async def stop_client(self):
        if self.client:
            await self.client.__aexit__()
            self.client = None  # type: ignore

        if self.browser:
            await self.browser.__aexit__()
            self.browser = None  # type: ignore

    async def crawl(self, forum: str, need: CrawlNeed = CrawlNeed()):
        await self.init_client()

        scan = Controller.config.scan
        raw_threads: list[aiotieba.typing.Thread] = []
        for i in range(1, scan.thread_page_forward + 1):
            async with self.eta:
                threads = await self.client.get_threads(forum, pn=i)
                raw_threads.extend(threads)

        for thread in raw_threads:
            updated = False
            thread_mark = f"{thread.last_time}.{thread.reply_num}"
            if (cache_thread_mark := self.cache.get(thread.pid)) is None:
                updated = thread.reply_num > 0
                yield Thread.from_aiotieba_data(thread)
            elif thread_mark != cache_thread_mark:
                updated = True

            if not updated or (not need.post and not need.comment):
                self.cache.set(thread.pid, thread_mark)
                continue

            raw_posts: list[Post] = []
            raw_comments: list[Comment] = []
            reply_num_dict: dict[int, int] = {}

            async def get_posts(pn):
                data = await self.browser.get_posts(thread.tid, pn=pn)
                raw_posts.extend(data.posts)
                raw_comments.extend(data.comments)
                reply_num_dict.update(data.reply_num)
                return data

            async with self.eta:
                data = await get_posts(1)

                if data.total_page < scan.post_page_forward + scan.post_page_backward:
                    for i in range(2, data.total_page + 1):
                        async with self.eta:
                            await get_posts(i)
                else:
                    for i in (2, scan.post_page_forward + 1):
                        async with self.eta:
                            await get_posts(i)
                    for i in range(
                        data.total_page,
                        data.total_page - scan.post_page_backward,
                        -1,
                    ):
                        async with self.eta:
                            await get_posts(i)

            self.cache.set(thread.pid, thread_mark)

            for post in raw_posts:
                reply_num = reply_num_dict.get(post.pid, 0)

                if post.floor == 1:
                    # 跳过一楼 （与主题帖相同
                    continue
                updated = False

                if (reply_num_cache := self.cache.get(post.pid)) is None:
                    updated = reply_num > 4
                    if need.post:
                        yield post
                elif reply_num != reply_num_cache:
                    updated = True

                if not updated or not need.post:
                    self.cache.set(post.pid, reply_num)
                    continue

                target_pn = (
                    reply_num // 30 + 1 if reply_num % 30 != 0 else reply_num // 30
                )
                async with self.eta:
                    raw_comments.extend(
                        Comment.from_aiotieba_data(i)
                        for i in await self.client.get_comments(
                            post.tid, post.pid, pn=target_pn
                        )
                    )

                self.cache.set(post.pid, reply_num)

                for comment in raw_comments:
                    if self.cache.get(comment.pid) is None:
                        self.cache.set(comment.pid, 1)
                        yield comment

    def save_cache(self):
        self.cache.save_data()

    @classmethod
    def delete_cacche(cls):
        cls.CACHE_FILE.unlink(missing_ok=True)


class CrawlerManager:
    crawler = Crawler()
    needs: dict[str, CrawlNeed] = {}
    task: asyncio.Task | None = None

    @classmethod
    async def update_needs(cls, _=None):
        new_needs = {}

        for user in UserManager.users.values():
            forum = user.config.forum

            if user.config.enable:
                need = CrawlNeed(
                    thread=forum.thread, post=forum.post, comment=forum.comment
                )
                if forum.forum in new_needs:
                    new_needs[forum.forum] += need
                else:
                    new_needs[forum.forum] = need

        cls.needs = new_needs
        await cls.start_or_stop()

    @classmethod
    async def start_or_stop(cls):
        if cls.needs and not cls.task:
            cls.task = asyncio.create_task(cls.crawl())
        if not cls.needs and cls.task:
            cls.task.cancel()
            cls.task = None

    @classmethod
    async def restart(cls, _: None = None):
        if cls.task:
            cls.task.cancel()
            cls.task = asyncio.create_task(cls.crawl())

    @classmethod
    async def crawl(cls):
        for forum, need in cls.needs.items():
            async for content in cls.crawler.crawl(forum, need):
                await Controller.DispatchContent.broadcast(content)

    @classmethod
    async def start(cls):
        await cls.crawler.init_client()


UserManager.UserChange.on(CrawlerManager.update_needs)
UserManager.UserConfigChange.on(CrawlerManager.update_needs)
Controller.MainConfigChange.on(CrawlerManager.restart)
