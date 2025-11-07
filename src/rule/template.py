from __future__ import annotations

import abc
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from src.schemas.process import ProcessObject

from .condition import ConditionTemplate

if TYPE_CHECKING:
    from src.schemas.process import ProcessObject


class ContentCondition(ConditionTemplate):
    """
    从内容中直接获取属性进行判断的Condition基类
    """

    _target_attribute: str | list[str]

    async def get_value(self, obj: ProcessObject):
        value = obj.content
        if isinstance(self._target_attribute, str):
            value = getattr(value, self._target_attribute)
        else:
            for attr in self._target_attribute:
                value = getattr(value, attr)

        return value


class TextOptions(BaseModel):
    text: str = ""
    is_regex: bool = False
    ignore_case: bool = False

    @property
    def valid(self):
        return bool(self.text)

    def model_post_init(self, __context) -> None:
        if self.is_regex:
            self._re = re.compile(self.text, flags=(re.IGNORECASE if self.ignore_case else 0))
        else:
            self._text = self.text.lower() if self.ignore_case else self.text


class TextCondition(ConditionTemplate):
    _series = "text"
    options: TextOptions

    async def check(self, obj: ProcessObject) -> bool:
        value = await self.get_value(obj)

        if not value:
            return False

        if self.options.is_regex:
            return bool(self.options._re.search(value))
        else:
            if self.options.ignore_case:
                return self.options._text in value.lower()
            else:
                return self.options.text in value


class LimiterOptions(BaseModel):
    max: float | None = None
    min: float | None = None
    eq: float | None = None

    def model_post_init(self, context) -> None:
        if self.eq is not None:
            self.max = self.min = self.eq

    @property
    def valid(self) -> bool:
        if self.max is not None:
            if self.min is None:
                return True
            else:
                return self.max >= self.min
        else:
            return self.min is not None


class LimiterCondition(ConditionTemplate):
    _series = "limiter"
    options: LimiterOptions

    async def check(self, obj: ProcessObject) -> bool:
        value = await self.get_value(obj)

        if self.options.max is not None and value > self.options.max:
            return False
        if self.options.min is not None and value < self.options.min:
            return False
        return True


class TimeOptions(BaseModel):
    start: str | None = None
    end: str | None = None
    _start_timestamp: float | None = None
    _end_timestamp: float | None = None

    @property
    def valid(self) -> bool:
        return bool(self.start or self.end)

    @staticmethod
    def strptime(time_string: str):
        return datetime.strptime(time_string, "%Y-%m-%d %H:%M:%S").timestamp()

    def model_post_init(self, context) -> None:
        try:
            if self.start:
                self._start_timestamp = self.strptime(self.start)
            if self.end:
                self._end_timestamp = self.strptime(self.end)
        except ValueError as e:
            raise ValueError("时间规则格式错误，请检查配置文件") from e


class TimeCondition(ConditionTemplate):
    _series = "time"
    options: TimeOptions

    async def check(self, obj: ProcessObject) -> bool:
        value = await self.get_value(obj)
        if isinstance(value, str):
            value = TimeOptions.strptime(value)
        if self.options._end_timestamp is not None and value > self.options._end_timestamp:
            return False
        if self.options._start_timestamp is not None and value < self.options._start_timestamp:
            return False
        return True


class CheckBoxOptions[T](BaseModel):
    values: list[T]

    @property
    def valid(self) -> bool:
        return bool(self.values)

    def model_post_init(self, context) -> None:
        self._set = set(getattr(self, "values", []))


class CheckBoxCondition[T](ConditionTemplate):
    _series = "checkbox"
    options: CheckBoxOptions[T]

    async def check(self, obj: ProcessObject) -> bool:
        value = await self.get_value(obj)
        return value in self.options._set


class SelectOption[T](BaseModel):
    value: T

    @property
    def valid(self) -> bool:
        return bool(self.value)


class SelectCondition[T](ConditionTemplate):
    _series = "select"
    options: SelectOption[T]

    async def check(self, obj: ProcessObject) -> bool:
        return await self.get_value(obj) == self.options.value
