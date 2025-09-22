from pydantic import BaseModel


class UpdateEventData[T](BaseModel):
    old: T
    new: T
