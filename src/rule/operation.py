from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, TypeAdapter

if TYPE_CHECKING:
    from src.process.typedef import ProcessObject

from src.tieba.info import TiebaInfo


class OperationTemplate(BaseModel):
    type: Any
    options: Any = None
    direct: bool = False

    def serialize(self) -> dict[str, Any]:
        data = {"type": self.type}  # type: ignore
        if self.options:
            data["options"] = self.options

        if self.direct:
            data["direct"] = self.direct

        return data

    async def store_data(self, obj: ProcessObject, data: dict[str, Any]) -> None:
        pass


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


class Operations:
    operation_classes = None

    @classmethod
    def register(cls, operation):
        if cls.operation_classes is None:
            cls.operation_classes = operation
        else:
            cls.operation_classes |= operation

        return operation

    @classmethod
    def deserialize(cls, operations: OPERATION_TYPE | dict[str, Any]) -> OperationGroup:
        if isinstance(operations, str):
            return OperationGroup(operations)
        else:
            adapter = TypeAdapter(cls.operation_classes)
            return OperationGroup([adapter.validate_python(i) for i in operations])  # type: ignore


class DeleteOptions(BaseModel):
    delete_thread_if_author: bool = False


@Operations.register
class Delete(OperationTemplate):
    type: Literal["delete"] = "delete"
    options: DeleteOptions = DeleteOptions()

    async def store_data(self, obj: ProcessObject, data: dict[str, Any]) -> None:
        if data.get("is_thread_author") is None:
            data["is_thread_author"] = await TiebaInfo.get_if_thread_author(obj)


class BlockOptions(BaseModel):
    day: int | None = 1
    reason: str = ""


@Operations.register
class Block(OperationTemplate):
    type: Literal["block"] = "block"
    options: BlockOptions = BlockOptions()
