from __future__ import annotations

from typing import TYPE_CHECKING

from src.rule.rule import Rule

if TYPE_CHECKING:
    from src.core.config import UserConfig
    from src.schemas.process import ProcessObject


class Processer:
    def __init__(self, config: UserConfig) -> None:
        raw_rules = [j for j in (Rule(i) for i in config.rules) if j.valid]
        self.rules = [i for i in raw_rules if not i.whitelist]
        self.whitelist_rules = [i for i in raw_rules if i.whitelist]

        self.config = config

    async def process(self, obj: ProcessObject) -> Rule | None:
        if (
            obj.content.fname != self.config.forum.fname
            or not getattr(self.config.forum, obj.content.type.lower(), False)
            or not self.config.enable
        ):
            return None

        for rule in self.whitelist_rules:
            if await rule.check(obj):
                return None

        valid_rule = None
        for rule in self.rules:
            if await rule.check(obj):
                if self.config.process.fast_process:
                    return rule
                if valid_rule is None:
                    valid_rule = rule

        return valid_rule
