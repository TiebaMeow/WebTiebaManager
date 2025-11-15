from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, TypeAdapter

from src.schemas.rule import ConditionInfo

if TYPE_CHECKING:
    from src.schemas.process import ProcessObject


class ConditionTemplate(BaseModel, abc.ABC):
    options: Any
    priority: int = 50  # 优先级，默认50，从高到低检查
    _show_unprocessed: bool = False  # 私有属性，控制未处理时的显示

    @property
    def key(self) -> str | None:
        """
        当相同type的条件有不同的判断值时，作为区分依据
        """
        return None

    async def resolve_context(self, obj: ProcessObject, processed: bool = False) -> str:
        """
        解析处理的信息，提供给日志等使用

        Args:
            obj (ProcessObject): 处理对象
            processed (bool): 是否经过处理
                即：当未被处理时，根据条件所消耗的资源决定是否进行获取
                如果消耗大（如API调用），返回 "<unprocessed>"
        """
        if self._show_unprocessed and not processed:
            return "<unprocessed>"
        return str(await self.get_value(obj))

    @property
    def id(self) -> str:
        """
        同id表示context相同的condition
        """
        if self.key is not None:
            return f"{self.type}:{self.key}"  # type: ignore
        else:
            return self.type  # type: ignore

    @abc.abstractmethod
    async def get_value(self, obj: ProcessObject) -> Any:
        """
        获取用于判断的值
        """
        raise NotImplementedError

    @abc.abstractmethod
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

    def __len__(self):
        return len(self.conditions)

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
