from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

from aiotieba.api.get_posts._classdef import FragImage_p
from aiotieba.api.get_threads._classdef import FragImage_t
from pydantic import BaseModel

if TYPE_CHECKING:
    import aiotieba.typing


class User(BaseModel):
    user_name: str
    nick_name: str
    user_id: int
    portrait: str
    level: int

    @staticmethod
    def from_aiotieba_data(
        data: aiotieba.typing.Thread | aiotieba.typing.Post | aiotieba.typing.Comment,
    ):
        return User(
            user_name=data.user.user_name,
            nick_name=data.user.nick_name,
            user_id=data.user.user_id,
            portrait=data.user.portrait,
            level=data.user.level,
        )

    @property
    def log_name(self) -> str:
        """
        Get log name
        """
        if self.user_name:
            return self.user_name
        elif self.portrait:
            return f"{self.nick_name}/{self.portrait}"
        else:
            return str(self.user_id)


class Image(BaseModel):
    hash: str
    width: int
    height: int
    src: str


class ContentInterface(ABC):
    # 当type=thread时，表示thread自身的title，当type=post或comment时，表示post或comment所处主题帖的title

    fname: str
    title: str | None = None
    text: str
    images: list[Image]
    create_time: int
    tid: int
    pid: int
    floor: int
    user: User

    @classmethod
    @abstractmethod
    def from_aiotieba_data(cls, data) -> ContentInterface:
        """
        Convert data to CommonStructure
        """
        ...

    @staticmethod
    @abstractmethod
    def get_images_from_aiotieba_contents(contents) -> list[Image]:
        """
        Get image from contents
        """
        ...


class BaseContent(BaseModel):
    fname: str
    title: str | None = None
    text: str
    images: list[Image]
    create_time: int
    tid: int
    pid: int
    floor: int
    user: User

    @property
    def mark(self):
        _type: Literal["thread", "post", "comment"] = self.type  # type: ignore

        if _type == "thread":
            return self.title
        elif _type == "post":
            return f"{self.title} {self.floor}楼"
        else:
            return f"{self.title} {self.floor}楼 楼中楼"

    @property
    def link(self):
        return f"https://tieba.baidu.com/p/{self.tid}" + (
            "" if self.type == "thread" else f"?pid={self.pid}#{self.pid}"  # type: ignore
        )


class Thread(BaseContent, ContentInterface):
    floor: int = 1
    last_time: int
    reply_num: int
    type: Literal["thread"] = "thread"

    @classmethod
    def from_aiotieba_data(cls, data: aiotieba.typing.Thread):
        return cls(
            fname=data.fname,
            title=data.title,
            text=data.text.removeprefix(data.title + "\n"),
            images=cls.get_images_from_aiotieba_contents(data.contents),
            create_time=data.create_time,
            tid=data.tid,
            pid=data.pid,
            user=User.from_aiotieba_data(data),
            last_time=data.last_time,
            reply_num=data.reply_num,
        )

    @staticmethod
    def get_images_from_aiotieba_contents(contents) -> list[Image]:
        return [
            Image(
                hash=content.hash,
                width=content.show_width,
                height=content.show_height,
                src=content.origin_src,
            )
            for content in contents
            if isinstance(content, FragImage_t)
        ]


class Post(BaseContent, ContentInterface):
    reply_num: int
    type: Literal["post"] = "post"

    @classmethod
    def from_aiotieba_data(cls, data: aiotieba.typing.Post, title: str | None = None):
        return cls(
            fname=data.fname,
            title=title,
            text=data.text,
            images=cls.get_images_from_aiotieba_contents(data.contents),
            create_time=data.create_time,
            tid=data.tid,
            pid=data.pid,
            floor=data.floor,
            reply_num=data.reply_num,
            user=User.from_aiotieba_data(data),
        )

    @staticmethod
    def get_images_from_aiotieba_contents(contents) -> list[Image]:
        """
        Find image from contents
        """
        return [
            Image(
                hash=content.hash,
                width=content.show_width,
                height=content.show_height,
                src=content.origin_src,
            )
            for content in contents
            if isinstance(content, FragImage_p)
        ]


class Comment(BaseContent, ContentInterface):
    type: Literal["comment"] = "comment"

    @classmethod
    def from_aiotieba_data(cls, data: aiotieba.typing.Comment, title: str | None = None):
        return cls(
            fname=data.fname,
            title=title,
            text=data.text,
            images=[],
            create_time=data.create_time,
            tid=data.tid,
            pid=data.pid,
            floor=data.floor,
            user=User.from_aiotieba_data(data),
        )

    @staticmethod
    def get_images_from_aiotieba_contents(contents) -> list[Image]:
        """
        Find image from contents
        """
        return []


Content = Thread | Post | Comment


class UpdateEventData[T](BaseModel):
    old: T
    new: T
