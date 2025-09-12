from pydantic import BaseModel, Field

from src.constance import BDUSS_MOSAIC, CONFIRM_EXPIRE, CONTENT_VALID_EXPIRE, STOKEN_MOSAIC
from src.rule.rule_set import RuleSetConfig
from src.util.tools import int_time


class UserInfo(BaseModel):
    username: str
    password: str
    token: str = ""
    password_last_update: int = Field(default_factory=int_time)


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
        if len(config.bduss) > 10:
            config.bduss = config.bduss[:6] + BDUSS_MOSAIC + config.bduss[-4:]
        if len(config.stoken) > 10:
            config.stoken = config.stoken[:6] + STOKEN_MOSAIC + config.stoken[-4:]
        return config


class UserConfig(BaseModel):
    user: UserInfo
    rule_sets: list[RuleSetConfig] = Field(default_factory=list)
    forum: ForumConfig = Field(default_factory=ForumConfig)
    process: ProcessConfig = Field(default_factory=ProcessConfig)
    enable: bool = True
    permission: UserPermission = Field(default_factory=UserPermission)
