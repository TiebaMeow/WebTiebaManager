from pathlib import Path

import tomlkit
import yaml
from pydantic import BaseModel

from core.db.config import DatabaseConfig

from .constance import BASE_DIR
from .server.config import ServerConfig, random_secret
from .tieba.config import ScanConfig


class SystemConfig(BaseModel, extra="ignore"):
    scan: ScanConfig = ScanConfig()
    server: ServerConfig = ServerConfig(key=random_secret())
    database: DatabaseConfig = DatabaseConfig(type="sqlite", path=str(BASE_DIR / "data.db"))
    cleanup_time: str = "04:00"  # 缓存清理时间，格式如 "HH:MM"


def read_config[T](path: Path, obj: type[T]) -> T:
    if path.exists():
        with path.open(encoding="utf8") as f:
            return obj.model_validate((tomlkit.load(f) if path.suffix == ".toml" else yaml.safe_load(f)) or {})  # type: ignore
    else:
        return obj.model_validate({})  # type: ignore


CONFIG_PATH = BASE_DIR / "config.toml"

system_config = read_config(CONFIG_PATH, SystemConfig)


def write_config(config, path: Path = CONFIG_PATH):
    with Path(path).open(mode="w", encoding="utf8") as f:
        if path.suffix == ".toml":
            tomlkit.dump(config.model_dump(), f)
        else:
            yaml.dump(config.model_dump(), f, allow_unicode=True, indent=2)
