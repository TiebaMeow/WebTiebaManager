from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, TypeAdapter

from src.schemas.rule import ConditionInfo

if TYPE_CHECKING:
    from src.schemas.process import ProcessObject


class ConditionTemplate(BaseModel, ABC):
    options: Any
    priority: int = 50  # 优先级，默认50，从高到低检查

    @abstractmethod
    async def check(self, obj: ProcessObject) -> bool:
        raise NotImplementedError

    @property
    def valid(self) -> bool:
        return self.options.valid


class ConditionGroup:
    def __init__(self, conditions: list[ConditionTemplate]) -> None:
        self.conditions: list[ConditionTemplate] = sorted(
            (i for i in conditions if i.valid), key=lambda x: x.priority, reverse=True
        )

    def __iter__(self):
        return iter(self.conditions)

    def serialize(self):
        return [condition.model_dump() for condition in self.conditions]

    @property
    def valid(self):
        return bool(len(self.conditions))


class Conditions:
    condition_classes = None  # 储存所有condition class，用于转化条件配置
    condition_dict: dict[str, type[ConditionTemplate]] = {}
    condition_info: dict[str, ConditionInfo] = {}

    @classmethod
    def register(
        cls,
        name: str,
        category: str,
        description: str = "无描述",
        default_options: Any = None,
        values: dict[str, str] | None = None,
    ):
        """
        注册条件

        Args:
            name (str): 条件名称 如 "用户名"
            category (str): 条件分类 如 "用户"
            description (str): 条件描述 note 目前webui未使用此值
            default_options (Any): 条件默认配置
            values (dict[str, str] | None): 用于CheckBox/Select，提供给网页端信息 {原键: 用户友好名称}
        """

        def wrapper(condition: type[ConditionTemplate]):
            nonlocal default_options

            if cls.condition_classes is None:
                cls.condition_classes = condition
            else:
                cls.condition_classes |= condition

            if default_options is None:
                default_options = {}

            if values:
                default_condition = condition(options={"values": list(values.keys()), "value": list(values.keys())[0]})
            else:
                default_condition = condition(options=default_options)
            try:
                condition_type = default_condition.type  # type: ignore
            except AttributeError as e:
                raise Exception("条件类型未定义") from e

            cls.condition_dict[condition_type] = condition  # type: ignore
            cls.condition_info[condition_type] = ConditionInfo(
                type=condition_type,
                name=name,
                category=category,
                description=description,
                series=getattr(default_condition, "_series", "custom"),
                values=values,
            )

            return condition

        return wrapper

    @classmethod
    def fix_category(cls, category: str):
        """
        固定分类

        Args:
            category (str): 规则分类 如 "用户"

        Returns:
            Callable: 装饰器 Conditions.register，移除了category参数
        """

        def _(
            name: str, description: str = "无描述", default_options: Any = None, values: dict[str, str] | None = None
        ):
            return cls.register(name, category, description=description, default_options=default_options, values=values)

        return _

    @classmethod
    def deserialize(cls, condition_config: list[dict]) -> ConditionGroup:
        if cls.condition_classes:
            adapter = TypeAdapter(cls.condition_classes)
            return ConditionGroup([adapter.validate_python(i) for i in condition_config])
        else:
            return ConditionGroup([])
