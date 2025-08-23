import asyncio
from typing import TypeVar, Generic, Callable, Awaitable, Any

T = TypeVar("T")


class EventListener:
    def __init__(self, fn: Callable, un_register: Callable) -> None:
        self.fn = fn
        self.un_register = un_register


class AsyncEvent(Generic[T]):
    def __init__(self) -> None:
        self._listeners: list[Callable[[T], Awaitable[None]]] = []

    def on(
        self, fn: Callable[[T], Awaitable[None]] | Callable[[T], None] | EventListener
    ):
        if isinstance(fn, EventListener):
            fn = fn.fn

        if not asyncio.iscoroutinefunction(fn):

            async def async_fn(data: T):
                fn(data)

        else:
            async_fn = fn  # type: ignore

        self._listeners.append(async_fn)

        def un_register():
            self._listeners.remove(async_fn)

        return EventListener(fn, un_register)

    async def broadcast(self, data: T):
        for listener in self._listeners:
            await listener(data)
