from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import BIGINT, JSON, DateTime, Integer, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, foreign, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from src.schemas.process import ConditionContext, RuleContext
from src.schemas.tieba import Image

if TYPE_CHECKING:
    from src.schemas.tieba import Content, User


class Base(DeclarativeBase):
    pass


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_with_tz():
    return datetime.now(SHANGHAI_TZ)


class ModelListType[T: BaseModel](TypeDecorator):
    impl = JSON
    cache_ok = True

    def __init__(self, ModelType: type[T] = Image, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._ModelType = ModelType

    def process_bind_param(self, value: list[T] | None, dialect) -> list[dict[str, Any]]:
        if value is None:
            return []
        return [i.model_dump(mode="json") for i in value]

    def process_result_value(self, value: list[dict[str, Any]] | None, dialect) -> list[T]:
        if value is None:
            return []
        model_type = self._ModelType
        return [model_type(**i) for i in value]

    @property
    def python_type(self):
        return list


class ForumModel(Base):
    __tablename__ = "forum"

    fname: Mapped[str] = mapped_column(String(255), primary_key=True)
    fid: Mapped[int] = mapped_column(BIGINT, index=True)

    contents: Mapped[list[ContentModel]] = relationship(
        "ContentModel",
        back_populates="forum",
        primaryjoin=lambda: ForumModel.fname == foreign(ContentModel.fname),
    )


class UserModel(Base):
    __tablename__ = "user"

    user_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    portrait: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    user_name: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    nick_name: Mapped[str] = mapped_column(String(255), nullable=True, index=True)

    level: Mapped[int] = mapped_column(Integer, nullable=True, default=0)  # deprecated: use UserLevelModel instead

    contents: Mapped[list[ContentModel]] = relationship(
        "ContentModel",
        back_populates="author",
        primaryjoin=lambda: UserModel.user_id == foreign(ContentModel.author_id),
    )

    @classmethod
    def from_user(cls, user: User) -> UserModel:
        return cls(user_id=user.user_id, portrait=user.portrait, user_name=user.user_name, nick_name=user.nick_name)


class UserLevelModel(Base):
    __tablename__ = "user_level"
    __table_args__ = (PrimaryKeyConstraint("user_id", "fname"),)

    user_id: Mapped[int] = mapped_column(BIGINT, nullable=False)
    fname: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)

    @classmethod
    def from_content(cls, content: Content) -> UserLevelModel:
        return cls(user_id=content.user.user_id, fname=content.fname, level=content.user.level)


class ContentModel(Base):
    __tablename__ = "content"

    pid: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    tid: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
    fname: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    create_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=True)
    floor: Mapped[int] = mapped_column(Integer, nullable=False)
    images: Mapped[list[Image]] = mapped_column(ModelListType(Image), nullable=False, default=list)
    type: Mapped[str] = mapped_column(String(255), nullable=False)

    last_time: Mapped[int | None] = mapped_column(BIGINT, nullable=True, default=None)
    reply_num: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    last_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, default=now_with_tz, onupdate=now_with_tz, nullable=False
    )

    author_id: Mapped[int] = mapped_column(BIGINT, index=True)

    forum: Mapped[ForumModel] = relationship(
        "ForumModel",
        back_populates="contents",
        primaryjoin=lambda: ForumModel.fname == foreign(ContentModel.fname),
    )
    author: Mapped[UserModel] = relationship(
        "UserModel",
        back_populates="contents",
        primaryjoin=lambda: UserModel.user_id == foreign(ContentModel.author_id),
    )

    @classmethod
    def from_content(cls, content: Content) -> ContentModel:
        return cls(
            pid=content.pid,
            tid=content.tid,
            fname=content.fname,
            title=content.title,
            text=content.text,
            create_time=datetime.fromtimestamp(content.create_time, tz=SHANGHAI_TZ),
            floor=content.floor,
            images=content.images,
            type=content.type,
            last_time=getattr(content, "last_time", None),
            reply_num=getattr(content, "reply_num", None),
            author_id=content.user.user_id,
        )


# class LifeModel(Base):
#     __tablename__ = "life"

#     pid: Mapped[int] = mapped_column(BIGINT, primary_key=True)
#     tid: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
#     create_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
#     process_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_with_tz, nullable=False)
#     data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
#     user: Mapped[str] = mapped_column(String(255), nullable=False)

#     content: Mapped[ContentModel] = relationship(
#         "ContentModel",
#         back_populates="life",
#         primaryjoin=lambda: ContentModel.pid == foreign(LifeModel.pid),
#     )


class ProcessLogModel(Base):
    __tablename__ = "process_log"
    __table_args__ = (PrimaryKeyConstraint("pid", "user"),)

    tid: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
    pid: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
    user: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    create_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    process_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_with_tz, nullable=False)
    result_rule: Mapped[str] = mapped_column(String(255), nullable=True)
    is_whitelist: Mapped[bool | None] = mapped_column(nullable=True)  # null时表示无匹配规则


class ProcessContextModel(Base):
    __tablename__ = "process_context"
    __table_args__ = (PrimaryKeyConstraint("pid", "user"),)

    pid: Mapped[int] = mapped_column(BIGINT, index=True, nullable=False)
    user: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    rules: Mapped[list[RuleContext]] = mapped_column(ModelListType(RuleContext), nullable=False, default=list)
    conditions: Mapped[list[ConditionContext]] = mapped_column(
        ModelListType(ConditionContext), nullable=False, default=list
    )
