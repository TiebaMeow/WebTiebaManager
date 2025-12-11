# 自动导入追踪器：为 src 包内函数在运行时打印 `run {func_name} {file}:{lineno}`
try:
    from . import _tracer  # noqa: F401
except Exception:
    # 如果追踪器导入失败，不影响包的正常使用
    pass
