import os
from pathlib import Path
from typing import Literal, TypeVar

import yaml
from pydantic import BaseModel

from .constance import BASE_DIR
from .tieba.config import ScanConfig

T = TypeVar("T")


class Config(BaseModel):
    scan: ScanConfig = ScanConfig()


def read_config(path: Path, obj: type[T]) -> T:
    if path.exists():
        with path.open(encoding="utf8") as f:
            return obj.model_validate(yaml.safe_load(f) or {})  # type: ignore
    else:
        return obj.model_validate({})  # type: ignore


CONFIG_PATH = BASE_DIR / "config.yaml"

config = read_config(CONFIG_PATH, Config)


def write_config(config, path: os.PathLike = CONFIG_PATH):
    with Path(path).open(mode="w", encoding="utf8") as f:
        yaml.dump(config.model_dump(), f, allow_unicode=True, indent=2)
