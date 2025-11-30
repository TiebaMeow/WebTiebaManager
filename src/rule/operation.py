from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from src.schemas.process import ProcessObject
from src.schemas.rule import OperationInfo
from src.tieba.info import TiebaInfo

if TYPE_CHECKING:
    from src.rule.option import OptionDesc
    from src.schemas.process import ProcessObject
    from src.user.user import User


class OperationTemplate(BaseModel):
    type: Any
    options: Any = None
    direct: bool = False
    _need_bawu: bool
    _option_descs: list[OptionDesc] | None = None

    def serialize(self) -> dict[str, Any]:
        data = {"type": self.type}  # type: ignore
        if self.options:
            data["options"] = self.options

        if self.direct:
            data["direct"] = self.direct

        return data

    async def store_data(self, obj: ProcessObject, data: dict[str, Any]) -> None:
        """
        储存判断所需的数据，提供给confirm储存使用

        Args:
            obj (ProcessObject): 处理对象
            data (dict[str, Any]): 用于储存数据的字典

        例如，判断是否为楼主需要调用 TiebaInfo.get_if_thread_author(obj) 并将结果储存在 data 中以供后续操作使用
        具体实现请参考各操作的实现
        """

    async def operate(
        self,
        obj: ProcessObject,
        user: User,
    ) -> None:
        """
        执行操作

        Args:
            obj (ProcessObject): 处理对象
            user (User): 执行操作的用户
        """


STR_OPERATION = Literal["ignore", "delete", "block", "delete_and_block"]
OPERATION_TYPE = STR_OPERATION | list[OperationTemplate]


class OperationGroup:
    def __init__(self, operations: OPERATION_TYPE) -> None:
        self.operations = operations

    def serialize(self) -> STR_OPERATION | list[dict[str, Any]]:
        if isinstance(self.operations, str):
            return self.operations  # type: ignore
        else:
            return [i.serialize() for i in self.operations]

    @property
    def direct_operations(self) -> OperationGroup | None:
        if isinstance(self.operations, str):
            return None
        else:
            operations = [i for i in self.operations if i.direct]
            if not operations:
                return None
            return OperationGroup(operations=operations)

    @property
    def no_direct_operations(self) -> OperationGroup:
        if isinstance(self.operations, str):
            return OperationGroup(self.operations)  # type: ignore
        else:
            operations = [i for i in self.operations if not i.direct]
            return OperationGroup(operations=operations)

    @staticmethod
    def deserialize(data: OPERATION_TYPE | dict[str, Any]):
        return Operations.deserialize(data)

    @property
    def need_bawu(self) -> bool:
        if isinstance(self.operations, str):
            return self.operations in ("delete", "delete_and_block", "block")
        else:
            return any(i._need_bawu for i in self.operations)


class Operations:
    operation_classes = None
    operation_info: dict[str, OperationInfo] = {}

    @classmethod
    def register(cls, name: str, category: str, description: str = "无描述", default_options: Any = None):
        def wrapper(operation: type[OperationTemplate]):
            nonlocal default_options

            if cls.operation_classes is None:
                cls.operation_classes = operation
            else:
                cls.operation_classes |= operation

            if default_options is None:
                default_options = {}

            try:
                default_operation = operation(options=default_options)  # type: ignore
            except Exception:
                return operation

            operation_type = default_operation.type

            if default_operation._option_descs:
                defined_option_keys: set[str] = set(default_operation.options.model_fields.keys())
                option_desc_keys: set[str] = set()
                for desc in default_operation._option_descs:
                    if desc.key in option_desc_keys:
                        raise ValueError(f"操作 {name} 定义了重复的参数信息: {desc.key}")
                    option_desc_keys.add(desc.key)

                if option_desc_keys - defined_option_keys:
                    raise ValueError(
                        f"操作 {name} 缺少定义的参数，参数 {option_desc_keys - defined_option_keys} 未在options中定义"
                    )

            cls.operation_info[operation_type] = OperationInfo(
                type=operation_type,
                name=name,
                category=category,
                description=description,
                option_descs=default_operation._option_descs,
            )

            return operation

        return wrapper

    @classmethod
    def deserialize(cls, operations: OPERATION_TYPE | dict[str, Any]) -> OperationGroup:
        if isinstance(operations, str):
            return OperationGroup(operations)
        else:
            adapter = TypeAdapter(cls.operation_classes)
            return OperationGroup([adapter.validate_python(i) for i in operations])  # type: ignore


class DeleteOptions(BaseModel):
    delete_thread_if_author: bool = False


@Operations.register("删除", "吧务操作", "删除帖子")
class Delete(OperationTemplate):
    type: Literal["delete"] = "delete"
    options: DeleteOptions = Field(default_factory=DeleteOptions)
    _need_bawu: bool = True

    async def store_data(self, obj: ProcessObject, data: dict[str, Any]) -> None:
        if data.get("is_thread_author") is None:
            data["is_thread_author"] = await TiebaInfo.get_if_thread_author(obj)

    async def operate(self, obj: ProcessObject, user: User) -> None:
        if (
            obj.content.type != "thread"
            and self.options.delete_thread_if_author
            and await TiebaInfo.get_if_thread_author(obj)
        ):
            await user.client.delete(obj.content, del_thread=True)
        else:
            await user.client.delete(obj.content)


class BlockOptions(BaseModel):
    day: int | None = 1
    reason: str = ""


@Operations.register("封禁", "吧务操作", "封禁用户")
class Block(OperationTemplate):
    _need_bawu: bool = True
    type: Literal["block"] = "block"
    options: BlockOptions = Field(default_factory=BlockOptions)

    async def operate(self, obj: ProcessObject, user: User) -> None:
        await user.client.block(
            obj.content,
            day=self.options.day or user.config.forum.block_day,
            reason=self.options.reason or user.config.forum.block_reason,
        )
