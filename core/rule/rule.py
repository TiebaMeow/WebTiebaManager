from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, TypeAdapter
from ..process.typedef import ProcessObject


class RuleInfo(BaseModel):
    type: str
    name: str
    category: str
    description: str


class RuleTemplate(BaseModel, ABC):
    options: Any
    priority: int = 50  # 优先级，默认50，从高到低检查

    @abstractmethod
    async def check(self, obj: ProcessObject) -> bool:
        raise NotImplementedError

    @property
    def valid(self) -> bool:
        return self.options.valid


class RuleGroup:
    def __init__(self, rules: list[RuleTemplate]) -> None:
        self.rules: list[RuleTemplate] = sorted(
            (i for i in rules if i.valid), key=lambda x: x.priority, reverse=True
        )

    def __iter__(self):
        return iter(self.rules)

    def serialize(self):
        return [rule.model_dump() for rule in self.rules]

    @property
    def valid(self):
        return bool(len(self.rules))


class Rules:
    rule_classes = None  # 储存所有rule class，用于转化规则配置
    rule_dict: dict[str, type[RuleTemplate]] = {}
    rule_info: dict[str, RuleInfo] = {}

    @classmethod
    def register(
        cls,
        name: str,
        category: str,
        description: str = "无描述",
        default_options: Any = None,
    ):
        def wrapper(rule: type["RuleTemplate"]):
            nonlocal default_options

            if cls.rule_classes is None:
                cls.rule_classes = rule
            else:
                cls.rule_classes |= rule

            if default_options is None:
                default_options = {}

            default_rule = rule(options=default_options)
            try:
                rule_type = default_rule.type  # type: ignore
            except AttributeError:
                raise Exception("规则类型未定义")

            cls.rule_dict[rule_type] = rule  # type: ignore
            cls.rule_info[rule_type] = RuleInfo(
                type=rule_type, name=name, category=category, description=description
            )

            return rule

        return wrapper

    @classmethod
    def fix_category(cls, category: str):
        def _(
            name: str,
            description: str = "无描述",
            default_options: Any = None,
        ):
            return cls.register(
                name, category, description=description, default_options=default_options
            )

        return _

    @classmethod
    def deserialize_rule(cls, rule_config: RuleTemplate) -> RuleTemplate:
        return cls.rule_classes.model_validate(rule_config)  # type: ignore

    @classmethod
    def deserialize(cls, rule_config: list[RuleTemplate]) -> RuleGroup:
        if cls.rule_classes:
            adapter = TypeAdapter(cls.rule_classes)
            return RuleGroup([adapter.validate_python(i) for i in rule_config])
        else:
            raise Exception("无有效规则，无法初始化")
