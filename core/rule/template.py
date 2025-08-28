import abc
import re

from pydantic import BaseModel

from core.process.typedef import ProcessObject

from .rule import RuleTemplate


class ContentRuleTemplate(abc.ABC):
    _target_attribute: str | list[str]

    @abc.abstractmethod
    async def _raw_check(self, value) -> bool:
        raise NotImplementedError

    async def check(self, obj: ProcessObject) -> bool:
        value = obj.content
        if isinstance(self._target_attribute, str):
            value = getattr(value, self._target_attribute)
        else:
            for attr in self._target_attribute:
                value = getattr(value, attr)

        return await self._raw_check(value)


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


class TextRule(ContentRuleTemplate, RuleTemplate):
    options: TextOptions

    async def _raw_check(self, value: str | None) -> bool:
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


class LimiterRule(ContentRuleTemplate, RuleTemplate):
    options: LimiterOptions

    async def _raw_check(self, value: int) -> bool:
        if self.options.max is not None and value > self.options.max:
            return False
        if self.options.min is not None and value < self.options.min:
            return False
        return True


class CheckBoxOptions[T](BaseModel):
    value: list[T]

    @property
    def valid(self) -> bool:
        return bool(self.value)

    def model_post_init(self, context) -> None:
        self._set = set(getattr(self, "value", []))


class CheckBoxRule[T](ContentRuleTemplate, RuleTemplate):
    options: CheckBoxOptions[T]

    async def _raw_check(self, value: T) -> bool:
        return value in self.options._set


class SelectOption[T](BaseModel):
    value: T

    @property
    def valid(self) -> bool:
        return bool(self.value)


class SelectRule[T](ContentRuleTemplate, RuleTemplate):
    options: SelectOption[T]

    async def _raw_check(self, value: T) -> bool:
        return value == self.options.value
