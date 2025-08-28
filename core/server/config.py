from typing import Literal

from pydantic import BaseModel, Field

from core.util.tools import int_time, random_secret


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 36800
    key: str
    secret_key: str = Field(default_factory=random_secret)
    log_level: Literal["info", "warning", "error"] = "warning"
    access_log: bool = False
    token_expire_days: int = 7
    key_last_update: int = Field(default_factory=int_time)
    encryption_method: Literal["plain", "md5"] = "plain"
    encryption_salt: str = Field(default_factory=random_secret)

    @property
    def url(self):
        return f"http://{self.host}:{self.port}"
