from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.config import RuleConfig
from src.rule.condition import ConditionGroup, Conditions
from src.schemas.process import ConditionContext

from .operation import OperationGroup, Operations

if TYPE_CHECKING:
    from src.schemas.process import ProcessObject


class Rule:
    def __init__(self, config: RuleConfig) -> None:
        self.name: str = config.name
        self.manual_confirm: bool = config.manual_confirm
        self.last_modify: int = config.last_modify
        self.whitelist: bool = config.whitelist
        self.force_record: bool = config.force_record

        self.operations: OperationGroup = Operations.deserialize(config.operations)  # type: ignore
        self.conditions: ConditionGroup = Conditions.deserialize(config.conditions)  # type: ignore

    async def check(self, obj: ProcessObject) -> bool:
        for i in self.conditions:
            if not await i.check(obj):
                return False

        return True

    def serialize(self):
        return RuleConfig(
            name=self.name,
            manual_confirm=self.manual_confirm,
            last_modify=self.last_modify,
            whitelist=self.whitelist,
            operations=self.operations.serialize(),
            conditions=self.conditions.serialize(),
        )

    async def resolve_context(self, obj: ProcessObject) -> list[ConditionContext]:
        context = [
            ConditionContext(type=condition.type, context=await condition.resolve_context(obj), key=None)  # type: ignore
            for condition in self.conditions
        ]
        return context

    @property
    def valid(self):
        return self.conditions.valid
