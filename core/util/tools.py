import asyncio
import platform
import secrets
import sys
import time
import uuid


def timestring():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def wait_and_exit():
    input("程序已结束...")
    sys.exit(0)
    raise KeyboardInterrupt


def int_time() -> int:
    return int(time.time())


def iter_progress():
    progress = ["-", "\\", "|", "/"]
    while True:
        yield from progress


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


def is_windows_server_2012() -> bool:
    # 先判断是否为Windows系统
    if platform.system() != "Windows":
        return False

    try:
        # 获取系统版本信息（适用于Windows环境）
        win_ver = sys.getwindowsversion()
        # 检查主版本号6且次版本号2（Server 2012的NT版本号为6.2或6.3，对应Server 2012 R2）

        version_check = win_ver.major == 6 and win_ver.minor in (2, 3)

        # 同时检查平台信息中的"2012"关键词（应对衍生系统）
        platform_check = "2012" in platform.platform().lower()

        return version_check or platform_check
    except AttributeError:  # 非Windows系统不会执行到此处
        return False


def uuid4() -> str:
    return uuid.uuid4().hex


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

    def __enter__(self):
        self.start_time = time.monotonic()
        return self

    def __exit__(self, exc_type=None, exc_val=None, exc_tb=None):
        self.costs.append(time.monotonic() - self.start_time)


def random_secret(length=32):
    return secrets.token_hex(length)
