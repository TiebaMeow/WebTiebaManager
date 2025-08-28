import os
from pathlib import Path
from typing import TypeVar

import toml
from pydantic import BaseModel

from .constance import BASE_DIR
from .server.config import ServerConfig, random_secret
from .tieba.config import ScanConfig

T = TypeVar("T")


class SystemConfig(BaseModel):
    scan: ScanConfig = ScanConfig()
    server: ServerConfig = ServerConfig(key=random_secret())


def read_config(path: Path, obj: type[T]) -> T:
    if path.exists():
        with path.open(encoding="utf8") as f:
            return obj.model_validate(toml.load(f) or {})  # type: ignore
    else:
        return obj.model_validate({})  # type: ignore


CONFIG_PATH = BASE_DIR / "config.toml"

system_config = read_config(CONFIG_PATH, SystemConfig)


def write_config(config, path: os.PathLike = CONFIG_PATH):
    with Path(path).open(mode="w", encoding="utf8") as f:
        toml.dump(config.model_dump(), f)
