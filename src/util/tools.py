import asyncio
import secrets
import time


def timestring():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def int_time() -> int:
    return int(time.time())


class EtaSleep:
    def __init__(self, cd: float):
        self.cd = cd
        self.eta = 0

    def refresh(self):
        self.eta = time.monotonic() + self.cd

    async def sleep_async(self):
        if self.remaining > 0:
            await asyncio.sleep(self.remaining)

    def sleep_sync(self):
        if self.remaining > 0:
            time.sleep(self.remaining)

    @property
    def remaining(self):
        return max(0, self.eta - time.monotonic())

    async def __aenter__(self):
        await self.sleep_async()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.refresh()

    def __enter__(self):
        self.sleep_sync()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.refresh()


class Timer:
    def __init__(self):
        self.start_time = 0
        self.costs = []

    @property
    def total_cost(self) -> float:
        return sum(self.costs)

    @property
    def avg_cost(self) -> float:
        return self.total_cost / len(self.costs) if self.costs else 0

    @property
    def last_cost(self) -> float:
        return self.costs[-1] if self.costs else 0

    @property
    def cost(self) -> float:
        return self.last_cost

    def __enter__(self):
        self.start_time = time.monotonic()
        return self

    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        self.costs.append(time.monotonic() - self.start_time)


def random_secret(length=32):
    return secrets.token_hex(length)
