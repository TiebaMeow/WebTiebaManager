from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.utils.tools import int_time, validate_password

from .tieba import Content  # noqa: TC001


class ConfirmSimpleData(BaseModel):
    content: Content
    process_time: int
    rule_set_name: str


class ConfirmData(ConfirmSimpleData):
    data: dict
    operations: str | list[dict[str, Any]]

    @property
    def simple(self) -> ConfirmSimpleData:
        return ConfirmSimpleData(content=self.content, process_time=self.process_time, rule_set_name=self.rule_set_name)


class UserInfo(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str
    code: str = ""
    password_last_update: int = Field(default_factory=int_time)

    @field_validator("password")
    @classmethod
    def validate_password_field(cls, v):
        if not validate_password(v):
            raise ValueError("密码格式不正确")
        return v


class UserPermission(BaseModel):
    can_edit_forum: bool = True  # 用户是否有权限编辑监控贴吧
    can_edit_rule_set: bool = True  # 用户是否有权限编辑规则集
