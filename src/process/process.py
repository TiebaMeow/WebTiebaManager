from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from src.db import Database
from src.models.models import SHANGHAI_TZ, ContextModel, now_with_tz
from src.rule.rule import Rule
from src.schemas.process import ConditionContext, ProcessRuleContext, RuleContext

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

        record_all = self.config.process.record_all

        contexts: list[ProcessRuleContext] = []

        for rule in self.whitelist_rules:
            result = await rule.check(obj)
            if result or record_all or rule.force_record:
                contexts.append(
                    ProcessRuleContext(
                        name=rule.name, whitelist=True, result=result, contexts=await rule.resolve_context(obj)
                    )
                )

            if result:
                # TODO 逻辑考虑 当fast_process设为false时，是否继续检查后续规则
                await self.resolve_context(obj, contexts, result_rule=rule)
                return None

        valid_rule = None
        for rule in self.rules:
            result = await rule.check(obj)
            if result or record_all or rule.force_record:
                contexts.append(
                    ProcessRuleContext(
                        name=rule.name, whitelist=False, result=result, contexts=await rule.resolve_context(obj)
                    )
                )

            if result:
                if self.config.process.fast_process:
                    await self.resolve_context(obj, contexts, result_rule=rule)
                    return rule
                if valid_rule is None:
                    valid_rule = rule

        await self.resolve_context(obj, contexts, result_rule=valid_rule)
        return valid_rule

    async def resolve_context(
        self,
        obj: ProcessObject,
        contexts: list[ProcessRuleContext],
        result_rule: Rule | None = None,
        auto_save: bool = True,
    ) -> ContextModel:
        conditions: list[ConditionContext] = []
        condition_identifier: list[str] = []
        condition_identifier_set: set[str] = set()

        rules: list[RuleContext] = []

        for rule_context in contexts:
            condition_indices = []

            for condition_context in rule_context.contexts:
                identifier = f"{condition_context.type}:{condition_context.key}"
                if identifier not in condition_identifier_set:
                    condition_identifier_set.add(identifier)
                    condition_identifier.append(identifier)
                    conditions.append(condition_context)

                condition_indices.append(condition_identifier.index(identifier))

            rules.append(
                RuleContext(
                    name=rule_context.name,
                    whitelist=rule_context.whitelist,
                    result=rule_context.result,
                    conditions=condition_indices,
                )
            )

        context = ContextModel(
            tid=obj.content.tid,
            pid=obj.content.pid,
            user=self.config.user.username,
            process_time=now_with_tz(),
            create_time=datetime.fromtimestamp(obj.content.create_time, tz=SHANGHAI_TZ),
            result_rule=result_rule.name if result_rule else None,
            whitelist=result_rule.whitelist if result_rule else None,
            rules=rules,
            conditions=conditions,
        )

        if auto_save:
            await Database.save_items((context,), on_conflict="upsert")

        return context
