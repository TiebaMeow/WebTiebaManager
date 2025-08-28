from pydantic import BaseModel, Field

from core.constance import CONTENT_VALID_EXPIRE
from core.rule.rule_set import RuleSetConfig
from core.util.tools import int_time


class UserInfo(BaseModel):
    username: str
    password: str
    token: str = ""
    password_last_update: int = Field(default_factory=int_time)


class ProcessConfig(BaseModel):
    mandatory_confirm: bool = False
    full_process: bool = False


class ForumConfig(BaseModel):
    block_day: int = 1
    block_reason: str = ""
    bduss: str = ""
    stoken: str = ""
    forum: str = ""
    thread: bool = True
    post: bool = True
    comment: bool = True
    content_validate_expire: int = CONTENT_VALID_EXPIRE

    @property
    def login_ready(self):
        return self.bduss and self.stoken


class UserConfig(BaseModel):
    user: UserInfo
    rule_sets: list[RuleSetConfig] = []
    forum: ForumConfig = ForumConfig()
    process: ProcessConfig = ProcessConfig()
    enable: bool = True
