from pathlib import Path

import tomlkit
import yaml
from pydantic import BaseModel, Field

from src.db.config import DatabaseConfig

from .constance import BASE_DIR
from .server import ServerConfig
from .tieba.config import ScanConfig


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

    def apply_new(self, new_config: "SystemConfig"):
        new_config = new_config.model_copy(deep=True)
        new_config.server = self.server.apply_new(new_config.server)
        new_config.database = self.database.apply_new(new_config.database)
        return new_config


def read_config[T](path: Path, obj: type[T]) -> T:
    if path.exists():
        with path.open(encoding="utf8") as f:
            return obj.model_validate((tomlkit.load(f) if path.suffix == ".toml" else yaml.safe_load(f)) or {})  # type: ignore
    else:
        return obj.model_validate({})  # type: ignore


def write_config(config, path: Path):
    with Path(path).open(mode="w", encoding="utf8") as f:
        if path.suffix == ".toml":
            tomlkit.dump(config.model_dump(exclude_none=True), f)
        else:
            yaml.dump(config.model_dump(), f, allow_unicode=True, indent=2)
