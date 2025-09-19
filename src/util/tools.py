import asyncio
import re
import secrets
import socket
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


class Mosaic:
    CHAR = "*"

    @staticmethod
    def mosaic(text: str, start: int = 1, end: int = 1, char: str | None = None) -> str:
        if not text:
            return ""
        start = max(0, start)
        end = max(0, end)
        if char is None:
            char = Mosaic.CHAR
        if len(text) <= start + end:
            return char * len(text)
        return text[:start] + char * (len(text) - start - end) + text[-end:]

    @staticmethod
    def full(text: str, char: str | None = None) -> str:
        if not text:
            return ""
        if char is None:
            char = Mosaic.CHAR
        return char * len(text)

    @staticmethod
    def compress(
        text: str, start: int = 1, end: int = 1, char: str | None = None, ratio: int = 2, min_length: int = 1
    ) -> str:
        if not text:
            return ""
        start = max(0, start)
        end = max(0, end)
        ratio = max(1, ratio)
        min_length = max(1, min_length)
        if char is None:
            char = Mosaic.CHAR
        if len(text) <= start + end + 2:
            return char * len(text)
        mosaic_len = max((len(text) - start - end) // ratio, min_length)
        return text[:start] + char * mosaic_len + text[-end:]

    @staticmethod
    def has_mosaic(text: str, char: str | None = None, min_length: int = 1) -> bool:
        if not text or min_length <= 0:
            return False
        if char is None:
            char = Mosaic.CHAR
        target = char * min_length
        return target in text


def get_listenable_addresses(with_default: bool = True, ipv6: bool = False) -> list[str]:
    """
    获取所有本机可监听的 IPv4 和 IPv6 地址（不含端口）。
    包含 127.0.0.1、::1 及所有网卡地址。

    Args:
        with_default (bool): 是否包含默认的回环地址
        ipv6 (bool): 是否包含 IPv6 地址
    """
    addresses = set()
    # 获取主机名
    hostname = socket.gethostname()
    # 获取所有IPv4地址
    try:
        if with_default:
            addresses.update(["127.0.0.1"])
        ipv4_list = socket.gethostbyname_ex(hostname)[2]
        for ip in ipv4_list:
            if ip:
                addresses.add(ip)
    except Exception:
        pass
    # 获取所有IPv6地址
    if ipv6:
        if with_default:
            addresses.update(["::1"])
        try:
            infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET6)
            for info in infos:
                ip = info[4][0]
                if ip:
                    addresses.add(ip)
        except Exception:
            pass
    return sorted(addresses)


def validate_password(password: str, max_length: int = 32) -> bool:
    r"""
    根据如下规则验证密码有效性
    - 允许的字符：大小写英文字母（A-Z, a-z）、数字（0-9）、以及以下 ASCII 符号:
    - !\"#$%&'()*+,-./:;<=>?@[\]^_`{|}~
    - 最大长度：密码长度不得超过 `max_length` 个字符（默认值：32）

    Returns:
        如果密码符合这些要求，返回 True，否则返回 False。
    """
    pattern = r"^[a-zA-Z0-9\x21-\x2F\x3A-\x40\x5B-\x60\x7B-\x7E]+$"
    return len(password) <= max_length and bool(re.match(pattern, password))
