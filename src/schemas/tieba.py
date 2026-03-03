from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Literal

from aiotieba.api.get_posts._classdef import FragImage_p
from aiotieba.api.get_threads._classdef import FragImage_t
from pydantic import BaseModel

if TYPE_CHECKING:
    import aiotieba.typing
    from tiebameow.models.dto import CommentDTO, PostDTO, ThreadDTO

    from src.models import ContentModel


class QrcodeStatus(Enum):
    WAITING = "WAITING"  # 等待扫码
    SCANNED = "SCANNED"  # 已扫码，等待确认
    EXPIRED = "EXPIRED"  # 二维码过期
    FAILED = "FAILED"  # 登录失败
    SUCCESS = "SUCCESS"  # 登录成功


class QrcodeData(BaseModel):
    imgurl: str = ""
    errno: int
    sign: str = ""
    prompt: str = ""


class AccountInfo(BaseModel):
    bduss: str
    stoken: str
    user_name: str


class QrcodeStatusData(BaseModel):
    status: QrcodeStatus
    account: AccountInfo | None = None


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

    @staticmethod
    def from_dto(dto: ThreadDTO | PostDTO | CommentDTO) -> User:
        return User(
            user_name=dto.author.user_name,
            nick_name=dto.author.nick_name,
            user_id=dto.author.user_id,
            portrait=dto.author.portrait,
            level=dto.author.level,
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

    @classmethod
    @abstractmethod
    def from_model(cls, model: ContentModel, user: User) -> ContentInterface:
        """
        Convert model to CommonStructure
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

    @staticmethod
    def get_images_from_dto(dto: ThreadDTO | PostDTO):
        return [
            Image(
                hash=image.hash,
                width=image.show_width,
                height=image.show_height,
                src=image.origin_src,
            )
            for image in dto.contents
            if image.type == "image"
        ]


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

    @classmethod
    def from_model(cls, model: ContentModel, user: User) -> Thread:
        return cls(
            fname=model.fname,
            title=model.title,
            text=model.text,
            images=model.images,
            create_time=int(model.create_time.timestamp()),
            tid=model.tid,
            pid=model.pid,
            user=user,
            last_time=model.last_time or 0,
            reply_num=model.reply_num or 0,
        )

    @classmethod
    def from_dto(cls, dto: ThreadDTO, pid: int = 0) -> Thread:
        return cls(
            fname=dto.fname,
            title=dto.title,
            text=dto.text,
            images=cls.get_images_from_dto(dto),
            create_time=int(dto.create_time.timestamp()),
            tid=dto.tid,
            pid=pid,
            user=User.from_dto(dto),
            last_time=int(dto.last_time.timestamp()),
            reply_num=dto.reply_num,
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

    @classmethod
    def from_model(cls, model: ContentModel, user: User) -> Post:
        return cls(
            fname=model.fname,
            title=model.title,
            text=model.text,
            images=model.images,
            create_time=int(model.create_time.timestamp()),
            tid=model.tid,
            pid=model.pid,
            floor=model.floor,
            reply_num=model.reply_num or 0,
            user=user,
        )

    @classmethod
    def from_dto(cls, dto: PostDTO, title: str | None = None) -> Post:
        return cls(
            fname=dto.fname,
            title=title,
            text=dto.text,
            images=cls.get_images_from_dto(dto),
            create_time=int(dto.create_time.timestamp()),
            tid=dto.tid,
            pid=dto.pid,
            floor=dto.floor,
            reply_num=dto.reply_num or 0,
            user=User.from_dto(dto),
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

    @classmethod
    def from_model(cls, model: ContentModel, user: User) -> Comment:
        return cls(
            fname=model.fname,
            title=model.title,
            text=model.text,
            images=model.images,
            create_time=int(model.create_time.timestamp()),
            tid=model.tid,
            pid=model.pid,
            floor=model.floor,
            user=user,
        )

    @classmethod
    def from_dto(cls, dto: CommentDTO, title: str | None = None) -> Comment:
        return cls(
            fname=dto.fname,
            title=title,
            text=dto.text,
            images=[],
            create_time=int(dto.create_time.timestamp()),
            tid=dto.tid,
            pid=dto.pid,
            floor=dto.floor,
            user=User.from_dto(dto),
        )

    @staticmethod
    def get_images_from_aiotieba_contents(contents) -> list[Image]:
        """
        Find image from contents
        """
        return []


Content = Thread | Post | Comment

Model2Content = {
    "thread": Thread.from_model,
    "post": Post.from_model,
    "comment": Comment.from_model,
}
