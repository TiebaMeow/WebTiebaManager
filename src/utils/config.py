from pathlib import Path

import tomlkit
import yaml


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
