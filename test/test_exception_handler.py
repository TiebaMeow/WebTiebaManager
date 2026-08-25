import asyncio
import json

import pytest

import src.api.server as server_mod
from src.api.server import app


def test_500_production_hides_exception_detail(monkeypatch):
    """非 DEV 环境：500 响应体不得包含异常字符串/内部路径。"""
    monkeypatch.setattr(server_mod, "DEV", False)

    async def direct_handle():
        return await server_mod.global_exception_handler(None, RuntimeError("SECRET_INTERNAL_PATH /home/secret/config.yaml"))  # type: ignore

    resp = asyncio.run(direct_handle())
    body = json.loads(resp.body)

    assert resp.status_code == 500
    assert body["message"] == "服务器内部错误"
    assert "detail" not in body
    assert "SECRET_INTERNAL_PATH" not in resp.body.decode()
    assert "config.yaml" not in resp.body.decode()


def test_500_dev_keeps_detail(monkeypatch):
    """DEV 环境保留 detail 便于开发。"""
    monkeypatch.setattr(server_mod, "DEV", True)

    async def direct_handle():
        return await server_mod.global_exception_handler(None, RuntimeError("some-debug-detail"))  # type: ignore

    resp = asyncio.run(direct_handle())
    body = json.loads(resp.body)

    assert resp.status_code == 500
    assert body["detail"] == "some-debug-detail"
