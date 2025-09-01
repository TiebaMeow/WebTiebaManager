from pydantic import BaseModel, Field

from core.constance import BDUSS_MOSAIC, CONTENT_VALID_EXPIRE, STOKEN_MOSAIC
from core.rule.rule_set import RuleSetConfig
from core.util.tools import int_time


class UserInfo(BaseModel):
    username: str
    password: str
    token: str = ""
    password_last_update: int = Field(default_factory=int_time)


class ProcessConfig(BaseModel):
    mandatory_confirm: bool = False
    fast_process: bool = False


class ForumConfig(BaseModel):
    block_day: int = 1
    block_reason: str = ""
    bduss: str = ""
    stoken: str = ""
    fname: str = ""
    thread: bool = True
    post: bool = True
    comment: bool = True
    content_validate_expire: int = CONTENT_VALID_EXPIRE

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
    rule_sets: list[RuleSetConfig] = []
    forum: ForumConfig = ForumConfig()
    process: ProcessConfig = ProcessConfig()
    enable: bool = True
