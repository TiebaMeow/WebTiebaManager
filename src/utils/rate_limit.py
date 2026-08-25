from __future__ import annotations

import time


class SlidingWindowRateLimiter:
    """
    内存滑动窗口限流器。

    以纯 IP 为键，记录窗口内的失败时间戳；窗口内失败次数达到上限后锁定。
    所有 mount 点（登录/注册/初始化）共享同一个实例、按 IP 全局计数，
    避免攻击者在不同端点间分散爆破绕过。

    参数（已与用户确认）：
        window: 窗口时长（秒），默认 15 分钟
        limit:  窗口内失败上限次数，默认 10 次
        lockout: 命中上限后的锁定时长（秒），默认 15 分钟
    """

    def __init__(self, window: float = 15 * 60, limit: int = 10, lockout: float = 15 * 60):
        self.window = window
        self.limit = limit
        self.lockout = lockout
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def _now(self) -> float:
        return time.monotonic()

    def _prune(self, ip: str, now: float) -> list[float]:
        """清理窗口外的失败记录，避免长运行内存无限增长。"""
        cutoff = now - self.window
        fails = self._failures.get(ip)
        if not fails:
            return []
        kept = [t for t in fails if t > cutoff]
        if kept:
            self._failures[ip] = kept
        else:
            self._failures.pop(ip, None)
        return kept

    def is_locked(self, ip: str) -> bool:
        """该 IP 当前是否处于锁定状态。"""
        now = self._now()
        until = self._locked_until.get(ip)
        if until is None:
            return False
        if until > now:
            return True
        # 锁定期已过，重置状态
        self._locked_until.pop(ip, None)
        self._failures.pop(ip, None)
        return False

    def record_failure(self, ip: str) -> bool:
        """记录一次失败。若由此触发锁定则返回 True。"""
        now = self._now()
        fails = self._prune(ip, now)
        fails.append(now)
        self._failures[ip] = fails
        if len(self._failures[ip]) >= self.limit:
            self._locked_until[ip] = now + self.lockout
            return True
        return False

    def clear(self, ip: str) -> None:
        """清除指定 IP 的失败记录与锁定状态（如登录/注册成功后调用）。"""
        self._failures.pop(ip, None)
        self._locked_until.pop(ip, None)

    def reset_all(self) -> None:
        """清空全部状态（测试用）。"""
        self._failures.clear()
        self._locked_until.clear()

    def failure_count(self, ip: str) -> int:
        return len(self._prune(ip, self._now()))


# 全局唯一实例：登录/注册/初始化三个挂载点共享、按纯 IP 全局计数（已确认）。
# 窗口 15 分钟、失败 10 次、锁定 15 分钟。
auth_rate_limiter = SlidingWindowRateLimiter(window=15 * 60, limit=10, lockout=15 * 60)
