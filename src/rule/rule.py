from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, TypeAdapter

if TYPE_CHECKING:
    from src.process.typedef import ProcessObject


class RuleInfo(BaseModel):
    """规则信息

    Attributes:
        type (str): 类型，如UserNameRule、IpRule等
        name (str): 用户友善的名称
        category (str): 分类，如用户、帖子等
        description (str): 描述
        series (str): 基本类型，如Text, Limiter
        values (dict[str, str] | None): 用于CheckBox/Select，提供给网页端信息 {原键: 用户友好名称}
    """

    type: str
    name: str
    category: str
    description: str
    series: str
    values: dict[str, str] | None = None


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
        self.rules: list[RuleTemplate] = sorted((i for i in rules if i.valid), key=lambda x: x.priority, reverse=True)

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
        values: dict[str, str] | None = None,  # 用于CheckBox/Select，提供给网页端信息
    ):
        def wrapper(rule: type[RuleTemplate]):
            nonlocal default_options

            if cls.rule_classes is None:
                cls.rule_classes = rule
            else:
                cls.rule_classes |= rule

            if default_options is None:
                default_options = {}

            if values:
                default_rule = rule(options={"values": list(values.keys()), "value": list(values.keys())[0]})
            else:
                default_rule = rule(options=default_options)
            try:
                rule_type = default_rule.type  # type: ignore
            except AttributeError as e:
                raise Exception("规则类型未定义") from e

            cls.rule_dict[rule_type] = rule  # type: ignore
            cls.rule_info[rule_type] = RuleInfo(
                type=rule_type,
                name=name,
                category=category,
                description=description,
                series=getattr(default_rule, "_series", "custom"),
                values=values,
            )

            return rule

        return wrapper

    @classmethod
    def fix_category(cls, category: str):
        def _(
            name: str, description: str = "无描述", default_options: Any = None, values: dict[str, str] | None = None
        ):
            return cls.register(name, category, description=description, default_options=default_options, values=values)

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
