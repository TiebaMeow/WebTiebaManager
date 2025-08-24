from hashlib import md5

from pydantic import BaseModel, Field

from core.constance import CONTENT_VALID_EXPIRE
from core.rule.rule_set import RuleSetConfig
from core.util.tools import uuid4


class UserInfo(BaseModel):
    username: str
    password: str
    token: str
    admin: bool = False
    secret: str = Field(default_factory=lambda: UserInfo.random_secret())

    @staticmethod
    def random_secret():
        """
        :return:
        长度为6的str字符
        """
        return md5(uuid4().encode("utf8")).hexdigest()[:6]


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
