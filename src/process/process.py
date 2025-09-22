from __future__ import annotations

from typing import TYPE_CHECKING

from src.rule.rule_set import RuleSet

if TYPE_CHECKING:
    from src.core.config import UserConfig
    from src.schemas.process import ProcessObject


class Processer:
    def __init__(self, config: UserConfig) -> None:
        raw_rule_sets = [j for j in (RuleSet(i) for i in config.rule_sets) if j.valid]
        self.rule_sets = [i for i in raw_rule_sets if not i.whitelist]
        self.whitelist_rule_sets = [i for i in raw_rule_sets if i.whitelist]

        self.config = config

    async def process(self, obj: ProcessObject) -> RuleSet | None:
        if (
            obj.content.fname != self.config.forum.fname
            or not getattr(self.config.forum, obj.content.type.lower(), False)
            or not self.config.enable
        ):
            return None

        for rule_set in self.whitelist_rule_sets:
            if await rule_set.check(obj):
                return None

        valid_rule_set = None
        for rule_set in self.rule_sets:
            if await rule_set.check(obj):
                if self.config.process.fast_process:
                    return rule_set
                if valid_rule_set is None:
                    valid_rule_set = rule_set

        return valid_rule_set
