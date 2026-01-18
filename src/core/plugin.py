from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import uuid
import zipfile
from typing import TYPE_CHECKING

from src.core.constants import CACHE_DIR, PLUGIN_DIR
from src.utils.logging import exception_logger, system_logger

if TYPE_CHECKING:
    from pathlib import Path


PLUGIN_CACHE_UUID = str(uuid.uuid4())

BASE_PLUGIN_CACHE_DIR: Path = CACHE_DIR / "plugins"
PLUGIN_CACHE_DIR = BASE_PLUGIN_CACHE_DIR / PLUGIN_CACHE_UUID


def load_plugins() -> None:
    """
    从插件目录加载所有插件。
    """
    if not PLUGIN_DIR.exists():
        PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
        return

    if not PLUGIN_DIR.is_dir():
        system_logger.error(f"插件目录不是一个有效的目录: {PLUGIN_DIR}")
        return

    # 当插件目录为空时，跳过加载
    if not any(PLUGIN_DIR.iterdir()):
        return

    # 准备缓存目录以解压插件
    BASE_PLUGIN_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 尝试清理旧的缓存目录
    for item in BASE_PLUGIN_CACHE_DIR.iterdir():
        if item.is_dir():
            try:
                shutil.rmtree(item, ignore_errors=True)
            except Exception:
                system_logger.warning(f"无法删除旧的插件缓存目录: {item}")

    # 使用唯一子目录避免删除整个目录带来的安全风险
    PLUGIN_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    system_logger.info("正在加载插件...")
    system_logger.debug(f"扫描插件目录: {PLUGIN_DIR}")
    system_logger.debug(f"插件缓存目录: {PLUGIN_CACHE_DIR}")
    for item in PLUGIN_DIR.iterdir():
        if item.name.startswith(("_", ".")):
            continue

        plugin_name = item.stem
        module_name = f"webtm_plugin_{item.stem}"
        entry_point: Path | None = None

        with exception_logger(f"加载插件 {item.name} 失败"):
            if item.is_file() and item.suffix == ".py":
                # 情况 1: .py 文件
                entry_point = item

            elif item.is_dir():
                # 情况 2: 目录中包含 plugin.py
                potential_entry = item / "plugin.py"
                if potential_entry.exists():
                    entry_point = potential_entry

            elif item.is_file() and item.suffix == ".zip":
                # 情况 3: Zip 文件
                extract_path = PLUGIN_CACHE_DIR / module_name

                try:
                    with zipfile.ZipFile(item, "r") as zf:
                        zf.extractall(extract_path)
                except zipfile.BadZipFile:
                    system_logger.error(f"无效的 zip 文件: {item.name}")
                    continue

                # 检查解压路径根目录下是否有 plugin.py
                root_plugin = extract_path / "plugin.py"
                if root_plugin.exists():
                    entry_point = root_plugin
                else:
                    # 检查是否有单个文件夹包含 plugin.py
                    # 过滤掉 __MACOSX 和隐藏文件/目录
                    extracted_items = [p for p in extract_path.iterdir() if not p.name.startswith(("_", "."))]

                    if len(extracted_items) == 1 and extracted_items[0].is_dir():
                        nested_plugin = extracted_items[0] / "plugin.py"
                        if nested_plugin.exists():
                            entry_point = nested_plugin

            if entry_point:
                system_logger.debug(f"加载插件: {plugin_name} 来自 {entry_point}")

                # 加载插件依赖
                added_paths = _load_plugin_libs(entry_point.parent, module_name)
                if added_paths is None:
                    system_logger.error(f"插件 {plugin_name} 依赖加载失败，跳过加载")
                    continue

                spec = importlib.util.spec_from_file_location(module_name, entry_point)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    system_logger.success(f"插件加载成功: {plugin_name}")

                    # 检查是否需要保留依赖路径
                    if not getattr(module, "KEEP_LIB", True):
                        for path in added_paths:
                            if path in sys.path:
                                sys.path.remove(path)
                                system_logger.debug(f"已从 sys.path 移除库路径: {path}")
                else:
                    system_logger.error(f"无法为插件创建 spec: {plugin_name}")


def load_lib_from_zip(zip_path: Path, lib_name: str | None = None, extract_dirname: str | None = None) -> str | None:
    """
    从 zip 文件加载库并将其路径添加到全局 sys.path。

    此函数会将指定的库（或整个 zip 的内容）解压到持久化的缓存目录中，
    并将解压后的路径插入到 `sys.path` 的开头，从而允许动态导入解压出的模块。

    副作用：
        - 修改全局 `sys.path`，将解压后的库路径插入其中。

    Zip 文件结构约定：
        - 如果提供了 `lib_name`，zip 文件应包含一个顶级目录或文件与该名称匹配，
          将仅解压该项并将其路径添加到 `sys.path`。
        - 如果 `lib_name` 为 None，则解压整个 zip 的内容，并将解压根目录添加到 `sys.path`。

    参数：
        zip_path (Path): zip 文件的路径。
        lib_name (str | None): 要解压并加载的库目录或文件名；为 None 时解压所有内容并将根目录添加到 `sys.path`。

    返回：
        str | None: 加载成功返回添加到 sys.path 的路径，失败返回 None。
    """
    if not zip_path.exists() or not zip_path.is_file():
        system_logger.error(f"指定的 zip 文件不存在: {zip_path}")
        return None

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            extract_path = PLUGIN_CACHE_DIR / "lib_cache" / (extract_dirname or zip_path.stem)
            extract_path.mkdir(parents=True, exist_ok=True)
            zf.extractall(extract_path)

            if lib_name:
                lib_path = extract_path / lib_name
                if lib_path.exists() and lib_path.is_dir():
                    if str(lib_path) not in sys.path:
                        sys.path.insert(0, str(lib_path))
                        system_logger.debug(f"已将库路径添加到 sys.path: {lib_path}")
                    return str(lib_path)
                else:
                    system_logger.error(f"指定的库文件不存在于解压路径中: {lib_name}")
                    return None
            else:
                if str(extract_path) not in sys.path:
                    sys.path.insert(0, str(extract_path))
                    system_logger.debug(f"已将解压路径添加到 sys.path: {extract_path}")
                return str(extract_path)

    except zipfile.BadZipFile:
        system_logger.error(f"无效的 zip 文件: {zip_path}")
        return None
    except Exception:
        system_logger.exception(f"解压 zip 文件 {zip_path} 时发生未知错误")
        return None


def _load_plugin_libs(plugin_dir: Path, module_name: str) -> list[str] | None:
    """
    加载插件目录下的依赖库 (lib.zip 或 lib[xxx].zip)。
    返回加载的路径列表，如果加载失败返回 None。
    """
    loaded_paths = []
    # 1. Check lib.zip
    lib_zip = plugin_dir / "lib.zip"
    if lib_zip.exists() and lib_zip.is_file():
        path = load_lib_from_zip(lib_zip, extract_dirname=module_name)
        if path is None:
            return None
        loaded_paths.append(path)

    # 2. Check lib[xxx].zip
    for item in plugin_dir.iterdir():
        if item.is_file() and item.suffix == ".zip":
            match = re.match(r"^lib\[(.+)\]\.zip$", item.name)
            if match:
                lib_name = match.group(1)
                path = load_lib_from_zip(item, extract_dirname=lib_name)
                if path is None:
                    return None
                loaded_paths.append(path)
    return loaded_paths
