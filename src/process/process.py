from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from src.db import Database
from src.models.models import SHANGHAI_TZ, ProcessContextModel, ProcessLogModel, now_with_tz
from src.rule.rule import CheckResult, ConditionGroup, Rule
from src.schemas.process import ConditionContext, RuleContext

if TYPE_CHECKING:
    from src.core.config import UserConfig
    from src.rule.condition import ConditionTemplate
    from src.schemas.process import ProcessObject


@dataclass
class ProcessRuleContext:
    name: str
    whitelist: bool
    result: bool
    conditions: ConditionGroup
    failed_step: int | None = None

    @classmethod
    def from_rule(cls, rule: Rule, check_result: CheckResult) -> ProcessRuleContext:
        return cls(
            name=rule.name,
            whitelist=rule.whitelist,
            result=check_result.result,
            failed_step=check_result.failed_step,
            conditions=rule.conditions,
        )


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

        record_all_context = self.config.process.record_all_context

        contexts: list[ProcessRuleContext] = []

        for rule in self.whitelist_rules:
            result = await rule.check(obj)
            if result or record_all_context or rule.force_record_context:
                contexts.append(ProcessRuleContext.from_rule(rule, result))

            if result:
                # TODO 逻辑考虑 当fast_process设为false时，是否继续检查后续规则
                await self.resolve(obj, contexts, result_rule=rule)
                return None

        valid_rule = None
        for rule in self.rules:
            result = await rule.check(obj)
            if result or record_all_context or rule.force_record_context:
                contexts.append(ProcessRuleContext.from_rule(rule, result))

            if result:
                if self.config.process.fast_process:
                    await self.resolve(obj, contexts, result_rule=rule)
                    return rule
                if valid_rule is None:
                    valid_rule = rule

        await self.resolve(obj, contexts, result_rule=valid_rule)
        return valid_rule

    async def resolve(
        self,
        obj: ProcessObject,
        contexts: list[ProcessRuleContext],
        result_rule: Rule | None = None,
        auto_save: bool = True,
    ) -> tuple[ProcessLogModel, ProcessContextModel]:
        """
        处理结果保存到数据库

        :Args:
            obj: 处理对象
            contexts: 处理上下文
            result_rule: 触发的规则
            auto_save: 是否自动保存到数据库

        :Returns:
            处理日志和处理上下文
        """

        conditions: list[ConditionTemplate] = []
        condition_identifier: list[str] = []
        condition_identifier_set: set[str] = set()
        processed_conditions: set[str] = set()

        rules: list[RuleContext] = []

        for rule_context in contexts:
            condition_indices = []
            processed_until = (
                rule_context.failed_step if rule_context.failed_step is not None else len(rule_context.conditions)
            )

            for i, condition in enumerate(rule_context.conditions):
                identifier = condition.id

                if i <= processed_until:
                    processed_conditions.add(identifier)

                if identifier not in condition_identifier_set:
                    condition_identifier_set.add(identifier)
                    condition_identifier.append(identifier)
                    conditions.append(condition)

                condition_indices.append(condition_identifier.index(identifier))

            rules.append(
                RuleContext(
                    name=rule_context.name,
                    whitelist=rule_context.whitelist,
                    result=rule_context.result,
                    conditions=condition_indices,
                    failed_step=rule_context.failed_step,
                )
            )

        log = ProcessLogModel(
            tid=obj.content.tid,
            pid=obj.content.pid,
            user=self.config.user.username,
            process_time=now_with_tz(),
            create_time=datetime.fromtimestamp(obj.content.create_time, tz=SHANGHAI_TZ),
            result_rule=result_rule.name if result_rule else None,
            is_whitelist=result_rule.whitelist if result_rule else None,
        )

        context = ProcessContextModel(
            pid=obj.content.pid,
            user=self.config.user.username,
            rules=rules,
            conditions=[
                ConditionContext(
                    type=i.type,  # type: ignore
                    key=i.key,
                    context=await i.resolve_context(obj, processed=(i.id in processed_conditions)),
                )
                for i in conditions
            ],
        )

        if auto_save:
            await Database.save_items((log,), on_conflict="upsert")
            await Database.save_items((context,), on_conflict="upsert")

        return log, context
