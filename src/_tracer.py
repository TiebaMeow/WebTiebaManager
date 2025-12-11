"""自动为 `src` 包中的函数添加运行时打印的轻量追踪器。

行为说明:
- 在模块导入时，遍历 `src` 目录下的所有子模块，导入并包装其中的函数与类方法。
- 包含对同步与异步函数的支持，调用时打印: `run {func_name} {file_name}:{lineno}`。

注意: 该模块在 `src.__init__` 中被导入以激活追踪。导入子模块可能会触发它们的顶级代码执行。
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
from functools import wraps
from pathlib import Path

PACKAGE = __package__ or "src"  # 应为 'src'；在某些导入上下文下 __package__ 可能为 None
PACKAGE_PATH = Path(__file__).parent


def _wrap_function(func):
    """返回包装器，调用时打印 run 信息并执行原函数。"""
    # wrapped_callable: 实际在模块中暴露的可调用对象（可能已被装饰）
    wrapped_callable = func
    # meta_target: 用于读取元信息（文件名/行号）的底层对象（如果存在 __wrapped__）
    meta_target = getattr(func, "__wrapped__", func)

    # 如果已标记为追踪过，则跳过再次包装，避免无限递归
    if getattr(wrapped_callable, "__traced__", False) or getattr(meta_target, "__traced__", False):
        return func

    # 预先读取所需的元信息，避免在函数调用时访问可能触发副作用的属性
    try:
        _fname = getattr(meta_target, "__name__", "<unknown>")
    except Exception:
        _fname = "<unknown>"

    try:
        _ffile = Path(meta_target.__code__.co_filename).name
        _flineno = meta_target.__code__.co_firstlineno
    except Exception:
        _ffile = getattr(meta_target, "__module__", "<unknown>")
        _flineno = 0

    # 包装时调用外层可调用对象以保留被装饰器包装的语义
    if inspect.iscoroutinefunction(wrapped_callable):
        @wraps(wrapped_callable)
        async def _async_wrapper(*args, __orig=wrapped_callable, **kwargs):
            print(f"run {_fname} {_ffile}:{_flineno}")
            return await __orig(*args, **kwargs)

        _async_wrapper.__traced__ = True
        try:
            wrapped_callable.__traced__ = True
            meta_target.__traced__ = True
        except Exception:
            pass
        return _async_wrapper

    @wraps(wrapped_callable)
    def _sync_wrapper(*args, __orig=wrapped_callable, **kwargs):
        print(f"run {_fname} {_ffile}:{_flineno}")
        return __orig(*args, **kwargs)

    _sync_wrapper.__traced__ = True
    try:
        wrapped_callable.__traced__ = True
        meta_target.__traced__ = True
    except Exception:
        pass
    return _sync_wrapper


def _wrap_class_methods(cls):
    for attr_name, attr in list(vars(cls).items()):
        if inspect.isfunction(attr):
            try:
                setattr(cls, attr_name, _wrap_function(attr))
            except Exception:
                pass


def wrap_module(module):
    """在给定模块中替换函数与类方法为包装器。"""
    for name, obj in list(vars(module).items()):
        try:
            # 仅包装该模块中定义的函数/类，避免影响其他模块（比如标准库）
            mod_name = getattr(obj, "__module__", None)
            if inspect.isfunction(obj) and mod_name == getattr(module, "__name__", None):
                setattr(module, name, _wrap_function(obj))
            elif inspect.isclass(obj) and mod_name == getattr(module, "__name__", None):
                _wrap_class_methods(obj)
        except Exception:
            # 避免因单个属性导致整体失败
            continue


def import_and_wrap_all():
    """导入 `src` 包下的所有子模块并进行包装。"""
    pkg = PACKAGE
    base = PACKAGE_PATH

    for path in base.rglob("*.py"):
        # 跳过自身和包初始化文件
        if path.name in {"_tracer.py", "__init__.py"}:
            continue

        rel = path.relative_to(base).with_suffix("")
        modname = pkg + "." + ".".join(rel.parts)
        try:
            m = importlib.import_module(modname)
        except Exception:
            # 某些模块在导入时可能会抛出异常，跳过它们
            continue

        try:
            wrap_module(m)
        except Exception:
            pass


# 先为已经加载到 sys.modules 中的 src 子模块添加包装器
for modname, mod in list(sys.modules.items()):
    if not isinstance(modname, str):
        continue
    if modname == PACKAGE or modname.startswith(PACKAGE + "."):
        try:
            if mod is not None:
                wrap_module(mod)
        except Exception:
            pass

# 再导入并包装所有子模块以覆盖尚未加载的部分
import_and_wrap_all()
