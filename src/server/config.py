from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.util.tools import Mosaic, int_time, random_secret, validate_password


class ServerConfig(BaseModel, extra="ignore"):
    host: str = "0.0.0.0"
    port: int = 36799
    key: str = Field(default_factory=lambda: random_secret(16))
    secret_key: str = Field(default_factory=random_secret)
    log_level: Literal["info", "warning", "error"] = "warning"
    access_log: bool = False
    token_expire_days: int = 7
    key_last_update: int = Field(default_factory=int_time)
    encryption_method: Literal["plain", "md5"] = "plain"
    encryption_salt: str = Field(default_factory=random_secret)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v):
        if not validate_password(v):
            raise ValueError("密钥格式不正确")
        return v

    @property
    def url(self):
        return f"http://{self.host}:{self.port}"

    @property
    def uvicorn_config_param(self):
        return {
            "host": self.host,
            "port": self.port,
            "log_level": self.log_level,
            "access_log": self.access_log,
        }

    @property
    def mosaic(self):
        config = self.model_copy()
        config.key = Mosaic.full(config.key)
        config.secret_key = Mosaic.compress(config.secret_key, 2, 0, ratio=8)
        config.encryption_salt = Mosaic.compress(config.encryption_salt, 2, 0, ratio=8)
        return config

    def apply_new(self, new_config: "ServerConfig"):
        new_config = new_config.model_copy(deep=True)
        mosaic_config = self.mosaic

        # 禁止覆盖 key_last_update
        new_config.key_last_update = self.key_last_update

        if new_config.key != self.key:
            if new_config.key == mosaic_config.key:
                new_config.key = self.key
            else:
                new_config.key_last_update = int_time()

        if new_config.token_expire_days != self.token_expire_days:
            self.secret_key = random_secret()

        if new_config.secret_key != self.secret_key:
            if new_config.secret_key == mosaic_config.secret_key:
                new_config.secret_key = self.secret_key

        if new_config.encryption_salt != self.encryption_salt:
            if new_config.encryption_salt == mosaic_config.encryption_salt:
                new_config.encryption_salt = self.encryption_salt

        return new_config
