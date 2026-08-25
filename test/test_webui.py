import asyncio
import json
import pathlib
import sys
import types

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

import src.api.routes.webui as webui  # noqa: E402
from src.api.server import app  # noqa: E402


async def raw_get(path: str):
    """以 ASGI scope 直接发起请求。path 为 ASGI 服务器解码后的路径。"""
    collected = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            collected.append(("start", msg))
        elif msg["type"] == "http.response.body":
            collected.append(("body", msg.get("body", b"")))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 123),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    return collected


def _status_and_text(collected):
    status = collected[0][1]["status"]
    text = b"".join(c[1] for c in collected if c[0] == "body").decode(errors="replace")
    return status, text


@pytest.fixture()
def isolated_cache(tmp_path, monkeypatch):
    """将 WEBUI_CACHE 指向临时目录，避免污染真实缓存。"""
    cache_dir = tmp_path / "webui"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webui, "WEBUI_CACHE", cache_dir)
    # 关闭本地覆盖/压缩包覆盖，保证走缓存与反代路径
    monkeypatch.setattr(webui, "LOCAL_OVERRIDE_ENABLED", False)
    return cache_dir


def test_assets_normal_read_within_cache(isolated_cache):
    (isolated_cache / "app.js").write_text("console.log(1)")

    status, text = _status_and_text(asyncio.run(raw_get("/assets/app.js")))

    assert status == 200
    assert text == "console.log(1)"


def test_assets_write_missing_then_cache(isolated_cache, monkeypatch):
    async def fake_proxy(url, request, raw=False):
        return b"NEW-CONTENT", 200, {"Content-Type": "text/javascript"}

    monkeypatch.setattr(webui, "reverse_proxy", fake_proxy)

    status, text = _status_and_text(asyncio.run(raw_get("/assets/new/thing.js")))

    assert status == 200
    assert text == "NEW-CONTENT"
    cached = isolated_cache / "new" / "thing.js"
    assert cached.read_text() == "NEW-CONTENT"


@pytest.mark.parametrize(
    "path",
    [
        "/assets/../../users/x/config.yaml",
        "/assets/../../config.toml",
        "/assets/a/../../b",
        "/assets/../other",
    ],
)
def test_assets_rejects_path_traversal(isolated_cache, path):
    status, _ = _status_and_text(asyncio.run(raw_get(path)))
    assert status == 400


def test_assets_symlink_escape_rejected(isolated_cache, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    secret = outside / "secret.txt"
    secret.write_text("SECRET")

    link = isolated_cache / "evil"
    link.symlink_to(secret, target_is_directory=False)

    status, _ = _status_and_text(asyncio.run(raw_get("/assets/evil")))
    assert status == 400


def test_assets_url_encoded_traversal_via_testclient(isolated_cache):
    """真实 HTTP 客户端会将 ..%2F 解码为 ../，经完整栈应返回 400。"""
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        for path in [
            "/assets/..%2F..%2Fusers/x/config.yaml",
            "/assets/%2e%2e/%2e%2e/x",
            "/assets/..%2Fconfig.toml",
        ]:
            assert client.get(path).status_code == 400


def test_normalize_relative_path_rejects_dotdot():
    for bad in ["../x", "a/../b", "a\\..\\b", "//../x"]:
        assert webui._normalize_relative_path(bad) is None

    assert webui._normalize_relative_path("a/b.js") == "a/b.js"
    assert webui._normalize_relative_path("./a") == "a"
