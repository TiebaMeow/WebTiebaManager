import hashlib
import json
import time
from typing import Literal, TypedDict

import aiofiles
import aiohttp
from pydantic import BaseModel, Field

from src.constance import BASE_DIR
from src.typedef import Comment, Image, Post, User
from src.util.logging import exception_logger, system_logger
from src.util.tools import timestring


class ResponseUser(TypedDict):
    name: str  # user_name
    portrait: str
    level_id: int  # level
    id: int  # user_id
    name_show: str  # nick_name


class TextContent(TypedDict):
    type: Literal[0]
    text: str


class EmojiContent(TypedDict):
    type: Literal[2]
    text: str  # 表情id
    c: str  # 表情说明


class ImageContent(TypedDict):
    type: Literal[3]
    bsize: str  # 'width,height'
    origin_src: str | None
    src: str


class ResponseBaseContent(TypedDict):
    author_id: int
    id: int  # pid
    time: int  # create_time
    content: list[TextContent | ImageContent]


class ResponseSubPost(TypedDict):
    pid: int
    sub_post_list: list[ResponseBaseContent]


class ResponsePost(ResponseBaseContent):
    author_id: int
    floor: int
    sub_post_number: int  # reply_num
    sub_post_list: ResponseSubPost


class ResponsePage(TypedDict):
    total_page: int
    has_more: int
    current_page: int


class ResponseThread(TypedDict):
    title: str
    id: int


class ResponseForum(TypedDict):
    name: str
    id: int


class GetPostsResponse(TypedDict):
    post_list: list[ResponsePost]
    user_list: list[ResponseUser]
    page: ResponsePage
    thread: ResponseThread
    forum: ResponseForum
    error_code: int
    error_msg: str | None


class GetPostData(BaseModel):
    posts: list[Post] = Field(default_factory=list)
    comments: list[Comment] = Field(default_factory=list)
    total_page: int = 0
    reply_num: dict[int, int] = Field(default_factory=dict)


class TiebaBrowser:
    def __init__(self) -> None:
        self._session = aiohttp.ClientSession()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type=None, exc_val=None, exc_tb=None):
        await self._session.close()

    @staticmethod
    def __add_sign(data):
        buffer = (
            "".join(
                "=".join((key, data[key]))
                for key in sorted(data.keys())
                if key != "sign" and isinstance(data[key], str)
            )
            + "tiebaclient!!!"
        )
        data["sign"] = hashlib.md5(buffer.encode("utf-8")).hexdigest()

    @staticmethod
    async def parse_data(data: GetPostsResponse):
        with exception_logger("爬虫数据解析失败"):
            if data["error_code"] != 0 or "post_list" not in data:
                return GetPostData()

            user_dict: dict[int, User] = {
                i["id"]: User(
                    user_name=i["name"],
                    nick_name=i["name_show"],
                    user_id=i["id"],
                    portrait=i["portrait"],
                    level=i["level_id"],
                )
                for i in data["user_list"]
            }
            posts: list[Post] = []
            comments: list[Comment] = []
            reply_num: dict[int, int] = {}

            for post in data["post_list"]:
                text = ""
                images = []

                for c in post.get("content", []):
                    if c["type"] == 0:
                        text += c["text"]
                    elif c["type"] == 3:
                        width, height = c["bsize"].split(",")
                        src = c.get("origin_src") or c["src"]
                        images.append(
                            Image(
                                hash=src.split("/")[-1].split(".")[0],
                                width=int(width),
                                height=int(height),
                                src=src,
                            )
                        )

                posts.append(
                    Post(
                        fname=data["forum"]["name"],
                        title=data["thread"]["title"],
                        user=user_dict[post["author_id"]],
                        text=text,
                        images=images,
                        create_time=post["time"],
                        tid=data["thread"]["id"],
                        pid=post["id"],
                        floor=post["floor"],
                        reply_num=post["sub_post_number"],
                    )
                )
                reply_num[post["id"]] = post["sub_post_number"]

                if "sub_post_list" not in post:
                    continue

                for comment in post["sub_post_list"]["sub_post_list"]:
                    text = ""
                    for c in comment["content"]:
                        if c["type"] == 0:
                            text += c["text"]

                    comments.append(
                        Comment(
                            fname=data["forum"]["name"],
                            title=data["thread"]["title"],
                            user=user_dict[comment["author_id"]],
                            text=text,
                            images=[],
                            create_time=comment["time"],
                            tid=data["thread"]["id"],
                            pid=comment["id"],
                            floor=post["floor"],
                        )
                    )

            return GetPostData(
                posts=posts,
                comments=comments,
                total_page=data["page"]["total_page"],
                reply_num=reply_num,
            )

        with exception_logger("保存爬虫错误数据失败"):
            error_filename = BASE_DIR / "logs" / f"fetch_post_{timestring().replace(':', '-').replace(' ', '_')}.json"
            async with aiofiles.open(error_filename, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
            system_logger.error(f"原始数据已保存至 {error_filename}")

        return GetPostData()

    def post(
        self,
        url,
        data=None,
        need_timestamp=False,
        need_sign=True,
        **kwargs,
    ):
        data = (
            {key: value if isinstance(value, str) else str(value) for key, value in data.items()}
            if data is not None
            else {}
        )
        if need_timestamp:
            data["timestamp"] = f"{time.time()}"
        if need_sign:
            self.__add_sign(data)
        return self._session.post(url, data=data, allow_redirects=False, **kwargs)

    async def get_posts(self, tid: int, pn: int = 1, rn: int = 30, comment_rn: int = 4, **kwargs) -> GetPostData:
        data = {
            "_client_type": 2,
            "_client_version": "7.0.0",
            "kz": tid,
            "pn": pn,
            "rn": rn,
            "with_floor": 1,
            "floor_rn": comment_rn,
        }  # type: ignore
        with exception_logger("获取帖子数据失败"):
            res = await self.post(
                "http://c.tieba.baidu.com/c/f/pb/page",
                data,
                **kwargs,
            )
            if res.status != 200:
                return GetPostData()

            return await self.parse_data(json.loads(await res.text()))
