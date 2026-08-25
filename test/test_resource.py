import io
import sys
import types
from datetime import UTC, datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

import src.api.auth as auth_mod
import src.api.routes.resource as resource_mod
import src.utils.logging as logging_mod
from src.api.server import app
from src.core.config import ServerConfig, SystemConfig
from src.core.controller import Controller
from src.user.manager import UserManager


@pytest.fixture(autouse=True)
def resource_env(monkeypatch):
    """隔离环境：真实 Controller.config + 注入一个测试用户 + 关闭真实网络。"""
    # 独立的 server 配置（固定 secret_key，避免随机）
    config = SystemConfig(server=ServerConfig(secret_key="test-secret-key" * 2))
    monkeypatch.setattr(Controller, "config", config, raising=False)
    monkeypatch.setattr(Controller, "running", False, raising=False)

    # 测试用户（最小化，仅满足 auth 依赖：get_user() -> .username / .config.user.username / .password_last_update）
    async def _noop_stop(*_a, **_k):
        return None

    stub_user = types.SimpleNamespace(
        username="alice",
        config=types.SimpleNamespace(user=types.SimpleNamespace(username="alice", password_last_update=111)),
        stop=_noop_stop,
    )

    old_users = dict(UserManager.users)
    UserManager.users["alice"] = stub_user  # type: ignore
    yield
    UserManager.users.clear()
    UserManager.users.update(old_users)


def _make_full_access_token(username="alice"):
    """构造一个合法的全权限登录 access token（与 /api/login 行为一致）。"""
    return auth_mod.create_access_token(
        data=auth_mod.TokenData(username=username, password_last_update=111, key_last_update=None).serialize()
    )


def _make_resource_token(username="alice", *, scope="resources", expires_delta=None, secret=None):
    secret = secret or Controller.config.server.secret_key
    now = datetime.now(UTC)
    payload = {"sub": username, "scope": scope, "iat": now}
    if expires_delta is not None:
        payload["exp"] = now + expires_delta
    else:
        payload["exp"] = now + timedelta(seconds=auth_mod.RESOURCE_TOKEN_TTL)
    return jwt.encode(payload, secret, algorithm=auth_mod.ALGORITHM)


def test_resource_token_endpoint_requires_login(resource_env):
    client = TestClient(app)
    r = client.post("/resources/token")
    assert r.status_code == 401


def test_resource_token_endpoint_issues_token(resource_env):
    client = TestClient(app)
    token = _make_full_access_token()
    r = client.post("/resources/token", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert "token" in data
    assert data["expires_in"] == auth_mod.RESOURCE_TOKEN_TTL

    # 校验返回的 token 可解码且 scope=resources
    payload = jwt.decode(data["token"], Controller.config.server.secret_key, algorithms=[auth_mod.ALGORITHM])
    assert payload["scope"] == "resources"
    assert payload["sub"] == "alice"
    assert "exp" in payload


@pytest.fixture
def fake_backend(monkeypatch):
    """模拟贴吧 meow 后端，避免真实网络。"""
    monkeypatch.setattr(Controller, "running", True, raising=False)

    async def fake_client():
        class FakeImage:
            img = None

        class FakeMeow:
            async def get_portrait(self, *a, **k):
                return FakeImage()

            async def hash2image(self, *a, **k):
                return FakeImage()

        return FakeMeow()

    monkeypatch.setattr(resource_mod.AnoymousTiebaMeow, "client", fake_client)
    monkeypatch.setattr(resource_mod, "ndarray2image", lambda img: io.BytesIO(b"WEBP-DATA"))
    return True


def _do_portrait(client, token=None, header=None, query=""):
    headers = {"Authorization": f"Bearer {header}"} if header else {}
    url = "/resources/portrait/abc" + (f"?token={token}" if token else "")
    if query:
        url += ("&" if "?" in url else "?") + query
    return client.get(url, headers=headers)


@pytest.mark.parametrize("bad_token", ["", "not-a-token", "abc.def.ghi"])
def test_get_portrait_rejects_invalid_token(resource_env, fake_backend, bad_token):
    client = TestClient(app)
    r = _do_portrait(client, token=bad_token)
    assert r.status_code == 401


def test_get_portrait_rejects_no_token(resource_env, fake_backend):
    client = TestClient(app)
    r = _do_portrait(client)
    assert r.status_code == 401


def test_get_portrait_rejects_expired_token(resource_env, fake_backend):
    tok = _make_resource_token(expires_delta=timedelta(minutes=-5))
    client = TestClient(app)
    assert _do_portrait(client, token=tok).status_code == 401


def test_get_portrait_rejects_wrong_scope(resource_env, fake_backend):
    full = _make_full_access_token()  # test 无 resources scope 的全权限 token 必须拒绝
    client = TestClient(app)
    assert _do_portrait(client, token=full).status_code == 401


def test_get_portrait_rejects_deleted_user(resource_env, fake_backend):
    UserManager.users.pop("alice")
    tok = _make_resource_token()
    client = TestClient(app)
    assert _do_portrait(client, token=tok).status_code == 401


def test_get_portrait_accepts_query_token(resource_env, fake_backend):
    tok = _make_resource_token()
    client = TestClient(app)
    r = _do_portrait(client, token=tok)
    assert r.status_code == 200
    assert r.content == b"WEBP-DATA"


def test_get_portrait_accepts_bearer_header(resource_env, fake_backend):
    tok = _make_resource_token()
    client = TestClient(app)
    r = _do_portrait(client, header=tok)
    assert r.status_code == 200


def test_get_image_accepts_token_with_size(resource_env, fake_backend):
    tok = _make_resource_token()
    client = TestClient(app)
    r = client.get(f"/resources/image/hash123?token={tok}&size=m")
    assert r.status_code == 200
    assert r.content == b"WEBP-DATA"


def test_get_portrait_503_when_not_running(resource_env, fake_backend, monkeypatch):
    # 后端不运行时应 503（在鉴权通过之后）
    monkeypatch.setattr(Controller, "running", False, raising=False)
    tok = _make_resource_token()
    client = TestClient(app)
    r = _do_portrait(client, token=tok)
    assert r.status_code == 503


def test_access_log_filter_suppresses_resources():
    f = logging_mod.ExcludeResourceAccessFilter()
    rec = logging_mod.logging.LogRecord(
        "uvicorn.access",
        20,
        "x",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "GET", "/resources/image/x?token=t", "1.1", 200),
        None,
    )
    assert f.filter(rec) is False

    rec2 = logging_mod.logging.LogRecord(
        "uvicorn.access",
        20,
        "x",
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "GET", "/assets/app.js", "1.1", 200),
        None,
    )
    assert f.filter(rec2) is True
