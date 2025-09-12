from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass
class EventListener:
    fn: Callable
    un_register: Callable


class AsyncEvent[T]:
    def __init__(self) -> None:
        self._listeners: list[Callable[[T], Awaitable[None]]] = []

    def on(self, fn: Callable[[T], Awaitable[None]] | Callable[[T], None] | EventListener):
        if isinstance(fn, EventListener):
            fn = fn.fn

        error_msg = "事件处理函数执行异常"

        from .logging import exception_logger

        if asyncio.iscoroutinefunction(fn):

            async def async_fn(data: T):
                with exception_logger(error_msg):
                    await fn(data)

        else:

            async def async_fn(data: T):
                with exception_logger(error_msg):
                    fn(data)

        self._listeners.append(async_fn)

        def un_register():
            self._listeners.remove(async_fn)

        return EventListener(fn, un_register)

    async def broadcast(self, data: T):
        await asyncio.gather(*(i(data) for i in self._listeners))
