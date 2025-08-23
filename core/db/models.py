from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import BIGINT, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, foreign, mapped_column, relationship


class Base(DeclarativeBase):
    pass


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_with_tz():
    return datetime.now(SHANGHAI_TZ)


class Content(Base):
    __tablename__ = "content"

    fid: Mapped[int] = mapped_column(BIGINT, primary_key=True)
    fname: Mapped[str] = mapped_column(String(255), index=True, nullable=False)


class Life(Base):
    __tablename__ = "life"

    user_id: Mapped[int] = mapped_column(BIGINT, primary_key=True)
