from pydantic import BaseModel

from src.rule.rule import RuleGroup, Rules

from ..process.typedef import ProcessObject
from .operation import STR_OPERATION, OperationGroup, Operations


class RuleSetConfig(BaseModel):
    name: str
    manual_confirm: bool = False
    operations: STR_OPERATION | list[dict]
    rules: list[dict]
    last_modify: int = 0
    whitelist: bool = False


class RuleSet:
    def __init__(self, config: RuleSetConfig) -> None:
        self.name: str = config.name
        self.manual_confirm: bool = config.manual_confirm
        self.last_modify: int = config.last_modify
        self.whitelist: bool = config.whitelist

        self.operations: OperationGroup = Operations.deserialize(config.operations)  # type: ignore
        self.rules: RuleGroup = Rules.deserialize(config.rules)  # type: ignore

    async def check(self, obj: ProcessObject) -> bool:
        for i in self.rules:
            if not await i.check(obj):
                return False

        return True

    def serialize(self):
        return RuleSetConfig(
            name=self.name,
            manual_confirm=self.manual_confirm,
            last_modify=self.last_modify,
            whitelist=self.whitelist,
            operations=self.operations.serialize(),
            rules=self.rules.serialize(),
        )

    @property
    def valid(self):
        return self.rules.valid
