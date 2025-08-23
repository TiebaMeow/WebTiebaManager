from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter


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
    def direct_opertions(self) -> "OperationGroup | None":
        if isinstance(self.operations, str):
            return None
        else:
            operataions = [i for i in self.operations if i.direct]
            if not operataions:
                return None
            return OperationGroup(operations=operataions)

    @property
    def no_direct_operations(self) -> "OperationGroup | None":
        if isinstance(self.operations, str):
            return OperationGroup(self.operations)  # type: ignore
        else:
            operations = [i for i in self.operations if not i.direct]
            if not operations:
                return None
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


@Operations.register
class Delete(OperationTemplate):
    type: Literal["Delete"] = "Delete"


class BlockOptions(BaseModel):
    day: int = 0
    reason: str = ""


@Operations.register
class Block(OperationTemplate):
    type: Literal["Block"] = "Block"
    options: BlockOptions = BlockOptions()


@Operations.register
class AuthorDelete(OperationTemplate):
    type: Literal["AuthorDelete"] = "AuthorDelete"
