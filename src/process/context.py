"""
运行时各个rule的处理状况
"""

from src.schemas.process import ConditionContext


class ProcessRuleContext:
    def __init__(self, name: str, whitelist: bool, result: bool = False) -> None:
        self.name: str = name
        self.whitelist: bool = whitelist
        self.result: bool = result
        self.contexts: list[ConditionContext] = []

    def add_context(self, type: str, value: str, key: str | None = None) -> None:  # noqa: A002
        self.contexts.append(ConditionContext(type=type, context=value, key=key))

    def set_result(self, result: bool) -> None:
        self.result = result
