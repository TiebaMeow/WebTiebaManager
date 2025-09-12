from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import BaseModel, computed_field


class DatabaseConfig(BaseModel, extra="ignore"):
    type: Literal["sqlite", "postgresql", "mysql"]
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
        elif self.type == "mysql":
            return (
                f"mysql+asyncmy://"
                f"{quote_plus(self.username)}:{quote_plus(self.password)}"  # type: ignore
                f"@{self.host}:{self.port}/{self.db}"
            )
        else:
            raise ValueError("Unsupported database type")
