"""P2-2：批量确认后台任务异常处理 + 每用户串行执行测试。"""

import asyncio
import time
import types

import pytest
from fastapi.testclient import TestClient
from loguru import logger

import src.api.auth as auth_mod
import src.api.routes.user as user_routes
from src.api.server import app
from src.core.config import ServerConfig, SystemConfig
from src.core.controller import Controller
from src.user.manager import UserManager
from src.user.user import User


class _ConfirmCacheStub:
    """内存 confirm 缓存，模拟 ExpireCache.get/delete 语义。"""

    def __init__(self, items: dict[int, object]):
        self._items = dict(items)

    async def get(self, pid):
        return self._items.get(pid)

    async def delete(self, pid):
        self._items.pop(pid, None)
        return True


def _fake_confirm(pid: int):
    """模拟 ConfirmData：仅提供 log 与 operate 所需的最小字段。"""
    return types.SimpleNamespace(
        pid=pid,
        content=types.SimpleNamespace(mark=f"mark-{pid}", tid=pid * 100, pid=pid),
    )


def make_user(
    confirm_pids: list[int],
    *,
    failing_pids: set[int] = frozenset(),
    delay: float = 0,
):
    """构造最小可用的 User 外观对象（绕过 User.__init__ 的重依赖，直接测试确认逻辑）。"""
    user = User.__new__(User)
    user._confirm_lock = asyncio.Lock()
    user.confirm = _ConfirmCacheStub({pid: _fake_confirm(pid) for pid in confirm_pids})
    user.logger = logger.bind(test="confirm")
    user.config = types.SimpleNamespace(user=types.SimpleNamespace(username="alice", password_last_update=111))
    user.executed_calls: list[tuple[int, str]] = []
    user._active = 0
    user._max_active = 0
    user._delay = delay
    user._failing_pids = set(failing_pids)

    async def operate_confirm(confirm, action):
        user._active += 1
        user._max_active = max(user._max_active, user._active)
        try:
            user.executed_calls.append((confirm.pid, action))
            if user._delay:
                await asyncio.sleep(user._delay)
            if confirm.pid in user._failing_pids:
                raise ValueError("无效的账号状态")
            # 模拟真实行为：执行成功后删除确认项
            await user.confirm.delete(confirm.pid)
        finally:
            user._active -= 1
        return True

    user.operate_confirm = operate_confirm  # type: ignore
    return user


def _make_token(username="alice"):
    return auth_mod.create_access_token(
        data=auth_mod.TokenData(username=username, password_last_update=111, key_last_update=None).serialize()
    )


def _wait_until(predicate, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---------- operate_confirms 单元测试 ----------


@pytest.mark.asyncio
async def test_operate_confirms_dedupes_and_executes_once():
    user = make_user([1, 2])
    results = await User.operate_confirms(user, [1, 1, 2], "execute")

    assert results == {1: True, 2: True}
    # 去重：同一 pid 只执行一次
    assert user.executed_calls == [(1, "execute"), (2, "execute")]
    # 成功后确认项被删除
    assert user.confirm._items == {}


@pytest.mark.asyncio
async def test_operate_confirms_missing_and_failed_items():
    user = make_user([1, 2], failing_pids={1})
    results = await User.operate_confirms(user, [1, 2, 99], "execute")

    # 失败项返回异常对象，缺失项返回 False，后续项继续执行
    assert isinstance(results[1], ValueError)
    assert results[2] is True
    assert results[99] is False
    # 失败确认保留以便重试；成功项已删除
    assert set(user.confirm._items) == {1}
    # 三项均被处理（缺失项不会触发 operate_confirm）
    assert user.executed_calls == [(1, "execute"), (2, "execute")]


@pytest.mark.asyncio
async def test_operate_confirms_serializes_concurrent_tasks():
    user = make_user([1, 2, 3, 4], delay=0.05)

    t1 = asyncio.create_task(User.operate_confirms(user, [1, 2], "execute"))
    t2 = asyncio.create_task(User.operate_confirms(user, [3, 4], "execute"))
    await asyncio.gather(t1, t2)

    # 两个并发调用被每用户锁串行化
    assert user._max_active == 1
    assert len(user.executed_calls) == 4
    assert user.confirm._items == {}


@pytest.mark.asyncio
async def test_confirm_many_catches_task_exceptions():
    user = make_user([1])

    async def boom(*_a, **_k):
        raise RuntimeError("boom")

    user.operate_confirms = boom  # type: ignore

    sink: list[str] = []

    def sink_fn(message):
        sink.append(str(message))

    sink_id = user.logger.add(sink_fn, level="ERROR")
    try:
        # 不应抛出未处理异常
        await user_routes.confirm_many(user, [1], "execute")
    finally:
        logger.remove(sink_id)

    assert any("批量确认任务异常终止" in record for record in sink)


# ---------- 路由测试 ----------


@pytest.fixture
def confirm_env(monkeypatch):
    config = SystemConfig(server=ServerConfig(secret_key="test-secret-key" * 2))
    monkeypatch.setattr(Controller, "config", config, raising=False)

    user = make_user([])
    old_users = dict(UserManager.users)
    UserManager.users["alice"] = user  # type: ignore
    yield user
    UserManager.users.clear()
    UserManager.users.update(old_users)


def test_confirm_single_not_found(confirm_env):
    with TestClient(app) as client:
        r = client.post(
            "/api/confirm/confirm",
            json={"pid": 999, "action": "execute"},
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
    assert r.json()["code"] == 400
    assert "内容不存在" in r.json()["message"]


def test_confirm_single_execute_success(confirm_env):
    confirm_env.confirm._items = {5: _fake_confirm(5)}
    with TestClient(app) as client:
        r = client.post(
            "/api/confirm/confirm",
            json={"pid": 5, "action": "execute"},
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
    assert r.json()["code"] == 200
    assert confirm_env.executed_calls == [(5, "execute")]
    assert confirm_env.confirm._items == {}


def test_confirm_single_account_not_logged_in_keeps_confirm(confirm_env):
    confirm_env._failing_pids = {6}
    confirm_env.confirm._items = {6: _fake_confirm(6)}
    with TestClient(app) as client:
        r = client.post(
            "/api/confirm/confirm",
            json={"pid": 6, "action": "execute"},
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
    assert r.json()["code"] == 400
    assert "账号未登录" in r.json()["message"]
    # 失败确认保留以便重试
    assert set(confirm_env.confirm._items) == {6}


def test_confirm_batch_background_handles_failures(confirm_env):
    confirm_env.confirm._items = {1: _fake_confirm(1), 2: _fake_confirm(2)}
    confirm_env._failing_pids = {2}

    with TestClient(app) as client:
        r = client.post(
            "/api/confirm/confirm",
            json={"pid": [1, 2], "action": "execute"},
            headers={"Authorization": f"Bearer {_make_token()}"},
        )
        assert r.json()["code"] == 200
        assert r.json()["message"] == "正在批量执行操作，请稍后查看结果"

        # 等待后台任务完成
        assert _wait_until(lambda: len(confirm_env.executed_calls) >= 2)

    # 成功项已执行并删除；失败项保留
    assert confirm_env.executed_calls == [(1, "execute"), (2, "execute")]
    assert set(confirm_env.confirm._items) == {2}


def test_confirm_batch_and_single_serialize_same_confirm_once(confirm_env):
    confirm_env.confirm._items = {1: _fake_confirm(1)}
    confirm_env._delay = 0.05

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {_make_token()}"}
        r_batch = client.post(
            "/api/confirm/confirm",
            json={"pid": [1], "action": "execute"},
            headers=headers,
        )
        r_single = client.post(
            "/api/confirm/confirm", json={"pid": 1, "action": "execute"}, headers=headers
        )

    assert r_batch.json()["code"] == 200
    # 并发下同一确认项只执行一次（另一个入口在锁内重新读取时已不存在）
    assert confirm_env.executed_calls == [(1, "execute")]
    assert confirm_env.confirm._items == {}
    # 后到的请求应得到"内容不存在"
    assert r_single.json()["code"] == 400
    assert "内容不存在" in r_single.json()["message"]