from __future__ import annotations

import importlib.util
import shutil
import sys
import uuid
import zipfile
from typing import TYPE_CHECKING

from src.core.constants import CACHE_DIR, PLUGIN_DIR
from src.utils.logging import system_logger

if TYPE_CHECKING:
    from pathlib import Path


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
    base_plugin_cache = CACHE_DIR / "plugins"
    base_plugin_cache.mkdir(parents=True, exist_ok=True)

    # 尝试清理旧的缓存目录
    for item in base_plugin_cache.iterdir():
        if item.is_dir():
            try:
                shutil.rmtree(item, ignore_errors=True)
            except Exception:
                pass

    # 使用唯一子目录避免删除整个目录带来的安全风险
    plugin_cache_dir = base_plugin_cache / str(uuid.uuid4())
    plugin_cache_dir.mkdir(parents=True, exist_ok=True)

    system_logger.info("正在加载插件...")
    system_logger.debug(f"扫描插件目录: {PLUGIN_DIR}")

    for item in PLUGIN_DIR.iterdir():
        if item.name.startswith(("_", ".")):
            continue

        module_name = f"webtm_plugin_{item.stem}"
        entry_point: Path | None = None

        try:
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
                extract_path = plugin_cache_dir / module_name

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
                system_logger.debug(f"加载插件: {module_name} 来自 {entry_point}")

                # 将入口点的父目录添加到 sys.path
                # 以便插件可以导入其自己的子模块
                # plugin_dir = entry_point.parent
                # if str(plugin_dir) not in sys.path:
                #     sys.path.insert(0, str(plugin_dir))

                spec = importlib.util.spec_from_file_location(module_name, entry_point)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    system_logger.success(f"插件加载成功: {module_name}")
                else:
                    system_logger.error(f"无法为插件创建 spec: {module_name}")

        except Exception:
            system_logger.exception(f"加载插件 {item.name} 时出错")
