import time
import json
import hashlib
import traceback
from typing import TypedDict, Literal

import aiohttp
from pydantic import BaseModel

from core.typedef import Post, Comment, User, Image
from core.util.tools import timestring


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
    posts: list[Post] = []
    comments: list[Comment] = []
    total_page: int = 0
    reply_num: dict[int, int] = {}


class TiebaBrowser:
    def __init__(self, BDUSS="", STOKEN="", tbs=""):
        self._BDUSS = BDUSS
        self._STOKEN = STOKEN
        self._tbs = tbs
        self._session = aiohttp.ClientSession()
        self._hd = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": "ka=open",
            "cuid": "baidutiebaapp21ce9427-2a0c-40de-b07c-4d185bc939c6;l",
            "User-Agent": "bdtb for Android 10.3.8.41",
            "Connection": "Keep-Alive",
            "cuid_galaxy2": "27591E20F4377A2A5EB340D71DAE60DA|VXQ5RBDUY",
            "client_user_token": "1969446685",
            "Accept-Encoding": "gzip",
            "client_logid": "1667064046918",
            "Host": "c.tieba.baidu.com",
        }
        self._hd2 = {"Cookie": f"BDUSS={self._BDUSS}; STOKEN={self._STOKEN};"}

    async def __aenter__(self):
        self._tbs = await self.get_tbs()
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

    async def get_tbs(self):
        async with self._session.get(
            "http://tieba.baidu.com/dc/common/tbs", headers=self._hd2
        ) as res:
            data = json.loads(await res.text())
        return data["tbs"]

    def post(
        self,
        url,
        data=None,
        need_tbs=False,
        need_timestamp=False,
        need_sign=True,
        **kwargs,
    ):
        data = (
            {
                key: value if isinstance(value, str) else str(value)
                for key, value in data.items()
            }
            if data is not None
            else {}
        )
        if need_tbs:
            data["tbs"] = self._tbs
        if need_timestamp:
            data["timestamp"] = "{0}".format(time.time())
        if need_sign:
            self.__add_sign(data)
        return self._session.post(url, data=data, allow_redirects=False, **kwargs)

    async def get_posts(
        self, tid: int, pn: int = 1, rn: int = 30, comment_rn: int = 4, **kwargs
    ) -> GetPostData:
        data = {
            "_client_type": 2,
            "_client_version": "7.0.0",
            "kz": tid,
            "pn": pn,
            "rn": rn,
            "with_floor": 1,
            "floor_rn": comment_rn,
        }  # type: ignore
        try:
            res = await self.post(
                "http://c.tieba.baidu.com/c/f/pb/page",
                data,
                need_tbs=True,
                headers=self._hd,
                **kwargs,
            )
            if res.status != 200:
                print(res.text)
                return GetPostData()

            data: GetPostsResponse = json.loads(await res.text())

            if data["error_code"] != 0:
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

                for c in post["content"]:
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
                        tid=tid,
                        pid=post["id"],
                        floor=post["floor"],
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
                            tid=tid,
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

        except Exception as e:
            try:
                with open("fetch_post_data.json", "wt", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                pass
            with open("fetch_post_error.txt", "at", encoding="utf-8") as f:
                f.write(f"-----{timestring()}-----\n")
                f.write(f"{traceback.format_exc()}\n\n")

            return GetPostData()
            raise e
