from pydantic import BaseModel, Field, field_validator

from src.constance import CONFIRM_EXPIRE, CONTENT_VALID_EXPIRE, COOKIE_MIN_MOSAIC_LENGTH
from src.rule.rule_set import RuleSetConfig
from src.util.tools import Mosaic, int_time, validate_password


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


class ProcessConfig(BaseModel):
    mandatory_confirm: bool = False
    fast_process: bool = True
    confirm_expire: int = CONFIRM_EXPIRE
    content_validate_expire: int = CONTENT_VALID_EXPIRE


class ForumConfig(BaseModel):
    block_day: int = 1
    block_reason: str = ""
    bduss: str = ""
    stoken: str = ""
    fname: str = ""
    thread: bool = True
    post: bool = True
    comment: bool = True

    @property
    def login_ready(self):
        return bool(self.bduss and self.stoken)

    @property
    def mosaic(self):
        config = self.model_copy()
        config.bduss = Mosaic.compress(config.bduss, 4, 2, min_length=COOKIE_MIN_MOSAIC_LENGTH, ratio=8)
        config.stoken = Mosaic.compress(config.stoken, 4, 2, min_length=COOKIE_MIN_MOSAIC_LENGTH, ratio=4)
        return config


class UserConfig(BaseModel):
    user: UserInfo
    rule_sets: list[RuleSetConfig] = Field(default_factory=list)
    forum: ForumConfig = Field(default_factory=ForumConfig)
    process: ProcessConfig = Field(default_factory=ProcessConfig)
    enable: bool = True
    permission: UserPermission = Field(default_factory=UserPermission)
