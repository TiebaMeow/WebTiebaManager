from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import AliasChoices, BaseModel, Field, computed_field, field_validator

from src.schemas.user import UserInfo, UserPermission
from src.utils.tools import Mosaic, get_listenable_addresses, int_time, random_secret, random_str, validate_password

from .constants import BASE_DIR, CONFIRM_EXPIRE, CONTENT_VALID_EXPIRE, COOKIE_MIN_MOSAIC_LENGTH


class ScanConfig(BaseModel, extra="ignore"):
    loop_cd: int = 10
    query_cd: float = 0.05
    thread_page_forward: int = 1
    post_page_forward: int = 1
    post_page_backward: int = 1
    comment_page_backward: int = 1


class DatabaseConfig(BaseModel, extra="ignore"):
    type: Literal["sqlite", "postgresql"]
    path: str | None = None
    username: str | None = None
    password: str | None = None
    host: str | None = None
    port: int | None = None
    db: str | None = None

    @computed_field
    @property
    def database_url(self) -> str:
        if self.type == "sqlite":
            if not self.path:
                raise ValueError("SQLite database path is required")
            url_path = Path(self.path).resolve().as_posix()
            return f"sqlite+aiosqlite:///{url_path}"
        if not all([self.username, self.password, self.host, self.port, self.db]):
            raise ValueError("Database configuration is incomplete")
        if self.type == "postgresql":
            return (
                f"postgresql+asyncpg://"
                f"{quote_plus(self.username)}:{quote_plus(self.password)}"  # type: ignore
                f"@{self.host}:{self.port}/{self.db}"
            )
        else:
            raise ValueError("Unsupported database type")

    @property
    def mosaic(self):
        config = self.model_copy()
        if config.password:
            config.password = Mosaic.full(config.password)
        return config

    def apply_new(self, new_config: DatabaseConfig):
        new_config = new_config.model_copy(deep=True)
        mosaic_config = self.mosaic

        if new_config.password != self.password:
            if new_config.password == mosaic_config.password:
                new_config.password = self.password

        return new_config


class ProcessConfig(BaseModel):
    mandatory_confirm: bool = False
    fast_process: bool = True
    confirm_expire: int = CONFIRM_EXPIRE
    content_validate_expire: int = CONTENT_VALID_EXPIRE
    record_all: bool = False


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


STR_OPERATION = Literal["ignore", "delete", "block", "delete_and_block"]


class RuleConfig(BaseModel):
    name: str
    manual_confirm: bool = False
    operations: STR_OPERATION | list[dict]
    # 兼容旧配置
    # TODO v1.0.0+ 移除
    conditions: list[dict] = Field(default_factory=list, validation_alias=AliasChoices("conditions", "rules"))
    last_modify: int = 0
    whitelist: bool = False
    force_record: bool = False


class UserConfig(BaseModel):
    user: UserInfo
    # 兼容旧配置
    # TODO v1.0.0+ 移除
    rules: list[RuleConfig] = Field(default_factory=list, validation_alias=AliasChoices("rules", "rule_sets"))
    forum: ForumConfig = Field(default_factory=ForumConfig)
    process: ProcessConfig = Field(default_factory=ProcessConfig)
    enable: bool = True
    permission: UserPermission = Field(default_factory=UserPermission)


class ServerConfig(BaseModel, extra="ignore"):
    host: str = "localhost"
    port: int = 36799
    key: str = Field(default_factory=lambda: random_str(16))
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
    def listenable_urls(self) -> list[str]:
        if self.host == "0.0.0.0":
            return [f"http://{addr}:{self.port}" for addr in get_listenable_addresses()]
        else:
            return [self.url]

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

    def apply_new(self, new_config: ServerConfig):
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
            new_config.secret_key = random_secret()

        if new_config.secret_key != self.secret_key:
            if new_config.secret_key == mosaic_config.secret_key:
                new_config.secret_key = self.secret_key

        if new_config.encryption_salt != self.encryption_salt:
            if new_config.encryption_salt == mosaic_config.encryption_salt:
                new_config.encryption_salt = self.encryption_salt

        return new_config


class SystemConfig(BaseModel, extra="ignore"):
    scan: ScanConfig = Field(default_factory=ScanConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(
        default_factory=lambda: DatabaseConfig(type="sqlite", path=str(BASE_DIR / "data.db"))
    )
    cleanup_time: str = "04:00"  # 缓存清理时间，格式如 "HH:MM"

    @property
    def mosaic(self):
        config = self.model_copy(deep=True)
        config.server = config.server.mosaic
        config.database = config.database.mosaic
        return config

    def apply_new(self, new_config: SystemConfig):
        new_config = new_config.model_copy(deep=True)
        new_config.server = self.server.apply_new(new_config.server)
        new_config.database = self.database.apply_new(new_config.database)
        return new_config
