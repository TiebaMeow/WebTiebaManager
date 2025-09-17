from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, computed_field

from src.util.tools import Mosaic


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

    def apply_new(self, new_config: "DatabaseConfig"):
        new_config = new_config.model_copy(deep=True)
        mosaic_config = self.mosaic

        if new_config.password != self.password:
            if new_config.password == mosaic_config.password:
                new_config.password = self.password

        return new_config
