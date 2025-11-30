from src.schemas.rule import CheckBoxDesc, InputDesc, NumberDesc, OptionDesc


class OptionDescMaker:
    def __init__(self) -> None:
        self._descs: list[OptionDesc] = []

    def input(
        self,
        key: str,
        label: str,
        placeholder: str | None = None,
        default: str = "",
        textarea: bool = False,
        password: bool = False,
    ):
        extra = {}
        if textarea:
            extra["textarea"] = True
        if password:
            extra["password"] = True

        self._descs.append(
            InputDesc(
                key=key,
                label=label,
                placeholder=placeholder,
                default=default,
                extra=extra,
            )
        )
        return self

    def number(self, key: str, label: str, placeholder: str | None = None, default: int | None = None):
        self._descs.append(NumberDesc(key=key, label=label, placeholder=placeholder, default=default))
        return self

    def checkbox(self, key: str, label: str, placeholder: str | None = None, default: bool = False):
        self._descs.append(CheckBoxDesc(key=key, label=label, placeholder=placeholder, default=default))
        return self

    def build(self):
        return self._descs
