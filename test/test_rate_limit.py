import asyncio
import sys
import time
import types

import fastapi
import pytest

# 注入最小可用的 src.control，避免真实依赖与循环导入
module = types.ModuleType("src.control")


class _DummyEvent:
    def on(self, *_args, **_kwargs):
        class _L:
            def un_register(self):
                return None

        return _L()


class _DummyController:
    Start = _DummyEvent()
    Stop = _DummyEvent()
    SystemConfigChange = _DummyEvent()
    DispatchContent = _DummyEvent()
    running = False
    config = None

    @classmethod
    async def start(cls):
        return None

    @classmethod
    async def stop(cls):
        return None


module.Controller = _DummyController  # type: ignore
sys.modules["src.control"] = module

from fastapi.testclient import TestClient  # noqa: E402

import src.api.auth as auth_mod  # noqa: E402
import src.api.routes.initialize as init_mod  # noqa: E402
import src.api.routes.system as system_mod  # noqa: E402
from src.api.server import Server, app  # noqa: E402
from src.core.controller import Controller  # noqa: E402
from src.utils.rate_limit import SlidingWindowRateLimiter, auth_rate_limiter  # noqa: E402


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    auth_rate_limiter.reset_all()
    Server._secure_key = None
    yield
    auth_rate_limiter.reset_all()
    Server._secure_key = None


# ---------- 限流器单元测试 ----------


def test_rate_limiter_locks_after_limit():
    rl = SlidingWindowRateLimiter(window=1000, limit=3, lockout=1000)
    assert rl.is_locked("1.2.3.4") is False
    rl.record_failure("1.2.3.4")
    rl.record_failure("1.2.3.4")
    assert rl.is_locked("1.2.3.4") is False
    assert rl.failure_count("1.2.3.4") == 2
    rl.record_failure("1.2.3.4")
    assert rl.is_locked("1.2.3.4") is True


def test_rate_limiter_per_ip_isolated():
    rl = SlidingWindowRateLimiter(window=1000, limit=2, lockout=1000)
    rl.record_failure("ip-a")
    rl.record_failure("ip-a")
    assert rl.is_locked("ip-a") is True
    assert rl.is_locked("ip-b") is False


def test_rate_limiter_window_expiry(monkeypatch):
    rl = SlidingWindowRateLimiter(window=10, limit=2, lockout=10)

    fake_now = [1000.0]

    def fake_time():
        return fake_now[0]

    monkeypatch.setattr(rl, "_now", fake_time)

    rl.record_failure("ip")
    rl.record_failure("ip")
    assert rl.is_locked("ip") is True

    # 锁定过期后自动恢复
    fake_now[0] = 1100.0
    assert rl.is_locked("ip") is False
    assert rl.failure_count("ip") == 0


def test_rate_limiter_clear():
    rl = SlidingWindowRateLimiter(window=1000, limit=2, lockout=1000)
    rl.record_failure("ip")
    rl.record_failure("ip")
    assert rl.is_locked("ip") is True
    rl.clear("ip")
    assert rl.is_locked("ip") is False
    assert rl.failure_count("ip") == 0


# ---------- 登录限流 ----------


@pytest.fixture
def fake_client(monkeypatch):
    """让认证始终失败，便于观察限流行为。"""
    async def always_fail(*_a, **_k):
        raise fastapi.HTTPException(status_code=401, detail="无效的用户名或密码")

    monkeypatch.setattr(auth_mod, "authenticate_user", always_fail)
    with TestClient(app) as client:
        yield client


def test_login_rate_limit_returns_429_after_limit(fake_client):
    auth_rate_limiter.limit = 3
    auth_rate_limiter.lockout = 60
    for _ in range(3):
        r = fake_client.post("/api/login", data={"username": "u", "password": "wrong"})
        assert r.status_code in (401, 429)
    # 第 4 次起应该 429
    for _ in range(2):
        r = fake_client.post("/api/login", data={"username": "u", "password": "wrong"})
        assert r.status_code == 429


def test_login_success_clears_failures(monkeypatch):
    """登录成功后清除该 IP 失败记录，正常用户不受限流影响。"""
    import src.user.manager as manager_mod

    class FakeUser:
        username = "realuser"

        class _Config:
            user = types.SimpleNamespace(password_last_update=123)

        config = _Config()

    async def auth_ok(*_a, **_k):
        return FakeUser()  # type: ignore

    async def sys_ok(*_a, **_k):
        return False

    monkeypatch.setattr(auth_mod, "authenticate_user", auth_ok)
    monkeypatch.setattr(auth_mod, "authenticate_system", sys_ok)
    monkeypatch.setattr(
        Controller,
        "config",
        types.SimpleNamespace(server=types.SimpleNamespace(token_expire_days=7, key_last_update=1, secret_key="test")),
        raising=False,
    )

    # 先制造两次失败
    auth_rate_limiter.record_failure("testclient")
    auth_rate_limiter.record_failure("testclient")
    assert auth_rate_limiter.failure_count("testclient") == 2

    with TestClient(app) as client:
        r = client.post("/api/login", data={"username": "realuser", "password": "right"})
        assert r.status_code == 200

    assert auth_rate_limiter.failure_count("testclient") == 0


# ---------- 注册限流 ----------


def test_register_invalid_code_counts_failure(monkeypatch):
    auth_rate_limiter.limit = 2
    auth_rate_limiter.lockout = 60

    async def no_code(*_a, **_k):
        return None

    monkeypatch.setattr(system_mod.CodeCache, "get", no_code)

    with TestClient(app) as client:
        body = {"username": "newuser", "password": "Passw0rd!", "code": "badcode"}
        r1 = client.post("/api/register", json=body)
        r2 = client.post("/api/register", json=body)
        assert r1.json()["code"] == 400
        assert r2.json()["code"] == 400
        r3 = client.post("/api/register", json=body)
        assert r3.status_code == 429


# ---------- 初始化限流 + 丢弃 _secure_key ----------


def test_initialize_wrong_key_rate_limited(monkeypatch):
    auth_rate_limiter.limit = 2
    auth_rate_limiter.lockout = 60

    monkeypatch.setattr(Server, "need_initialize", lambda: True)
    monkeypatch.setattr(Server, "secure_key", lambda: "test-secure-key")

    with TestClient(app) as client:
        body = {"secure_key": "wrong-key"}
        r1 = client.post("/api/initialize/initialize", json=body)
        r2 = client.post("/api/initialize/initialize", json=body)
        assert r1.status_code == 400
        assert r2.status_code == 400
        r3 = client.post("/api/initialize/initialize", json=body)
        assert r3.status_code == 429


def test_initialize_success_discards_secure_key(monkeypatch):
    auth_rate_limiter.limit = 2
    auth_rate_limiter.lockout = 60

    # lifespan 在 need_system=False 时会读取 Controller.config.server，需注入真实配置
    from src.core.config import SystemConfig

    monkeypatch.setattr(Controller, "config", SystemConfig())

    async def shutdown_task(*_a, **_k):
        return None

    async def new_user(*_a, **_k):
        return None

    monkeypatch.setattr(Server, "need_initialize", lambda: True)
    monkeypatch.setattr(Server, "need_user", lambda: True)
    monkeypatch.setattr(Server, "need_system", lambda: False)
    monkeypatch.setattr(Server, "secure_key", lambda: "test-secure-key")
    monkeypatch.setattr(Server, "shutdown_task", shutdown_task)
    monkeypatch.setattr(system_mod.UserManager, "new_user", new_user)

    Server._secure_key = "before-init"

    with TestClient(app) as client:
        body = {"secure_key": "test-secure-key", "user": {"username": "admin", "password": "Passw0rd!"}}
        r = client.post("/api/initialize/initialize", json=body)
        assert r.status_code == 200

    assert Server._secure_key is None
    # 初始化成功后该 IP 的失败/锁定状态被清除
    assert not auth_rate_limiter.is_locked("testclient")
    assert auth_rate_limiter.failure_count("testclient") == 0


# ---------- 账号存在性不泄露（dummy 校验路径） ----------


def test_authenticate_user_nonexistent_runs_dummy_verify(monkeypatch):
    # 用户不存在也走校验路径，避免时序泄露
    calls = []

    def fake_get_user(_name):
        return None

    def fake_verify(plain, stored):
        calls.append((plain, stored))
        return False

    monkeypatch.setattr(auth_mod.UserManager, "get_user", fake_get_user)
    monkeypatch.setattr(auth_mod, "verify_password", fake_verify)

    with pytest.raises(fastapi.HTTPException) as exc_info:
        asyncio.run(auth_mod.authenticate_user("ghost", "somepass"))
    assert exc_info.value.status_code == 401
    assert len(calls) == 1
    assert calls[0][1] == auth_mod.DUMMY_PASSWORD_HASH
