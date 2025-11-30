from typing import Any, Literal

from pydantic import BaseModel, Field


class BaseDesc(BaseModel):
    key: str
    label: str
    placeholder: str | None = None
    default: Any = None
    extra: dict[str, Any] = Field(default_factory=dict)


class InputDesc(BaseDesc):
    type: Literal["input"] = "input"
    default: str = ""


class NumberDesc(BaseDesc):
    type: Literal["number"] = "number"
    default: int | None = None


class CheckBoxDesc(BaseDesc):
    type: Literal["checkbox"] = "checkbox"
    default: bool = False


OptionDesc = InputDesc | NumberDesc | CheckBoxDesc


class ConditionInfo(BaseModel):
    """
    条件信息

    Attributes:
        type (str): 类型，如UserNameCondition、IpCondition等
        name (str): 用户友善的名称
        category (str): 分类，如用户、帖子等
        description (str): 描述
        series (str): 基本类型，如Text, Limiter
        values (dict[str, str] | None): 用于CheckBox/Select，提供给网页端信息 {原键: 用户友好名称}
        option_descs (None | list[OptionDesc]): 参数信息列表，仅在series为custom时生效
    """

    type: str
    name: str
    category: str
    description: str
    series: str
    values: dict[str, str] | None = None
    option_descs: None | list[OptionDesc] = None


class OperationInfo(BaseModel):
    """
    操作信息

    Attributes:
        type (str): 类型，如Delete / Block等
        name (str): 用户友善的名称
        category (str): 分类，如吧务操作等
        description (str): 描述
        option_descs (None | list[OptionDesc]): 参数信息列表，仅在type非内置处理时生效

    """

    type: str
    name: str
    category: str
    description: str
    option_descs: None | list[OptionDesc] = None
