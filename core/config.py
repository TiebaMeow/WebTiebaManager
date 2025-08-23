import os
from pathlib import Path
from typing import TypeVar, Literal

import yaml
from pydantic import BaseModel

from .constance import BASE_DIR
from pydantic import BaseModel

from .tieba.config import ScanConfig

T = TypeVar("T")


class Config(BaseModel):
    scan: ScanConfig = ScanConfig()


def read_config(path: Path, obj: type[T]) -> T:
    if path.exists():
        with open(path, mode="rt", encoding="utf8") as f:
            return obj.model_validate((yaml.safe_load(f) or {}))  # type: ignore
    else:
        return obj.model_validate({})  # type: ignore


CONFIG_PATH = BASE_DIR / "config.yaml"

config = read_config(CONFIG_PATH, Config)


def write_config(config: Config, path: os.PathLike = CONFIG_PATH):
    with open(path, mode="wt", encoding="utf8") as f:
        yaml.dump(config.model_dump(), f, allow_unicode=True, indent=2)
