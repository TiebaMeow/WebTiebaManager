"""P2-7：邀请码创建去除无效循环 + 消除 TOCTOU 竞争测试。"""

import asyncio
import types

import pytest

import src.api.routes.system as system_mod
import src.user.manager as manager_mod
import src.user.user as user_mod
from src.schemas.user import UserPermission
from src.user.manager import UserManager
from src.utils.cache import ExpireCache
from src.utils.rate_limit import auth_rate_limiter


def make_req(code: str, username: str = ""):
    return system_mod.UserInfodata(
        username=username,
        permission=UserPermission(),
        forum="forum1",
        code=code,
        use=False,
    )


@pytest.fixture
def invite_env(monkeypatch, tmp_path):
    # 内存 CodeCache，避免写入仓库 BASE_DIR/code
    monkeypatch.setattr(system_mod, "CodeCache", ExpireCache(expire_time=60, directory=None))
    # 用户数据目录隔离到临时目录
    monkeypatch.setattr(user_mod, "USER_DIR", tmp_path / "users")
    monkeypatch.setattr(manager_mod, "USER_DIR", tmp_path / "users")

    old_users = dict(UserManager.users)
    UserManager.users.clear()
    auth_rate_limiter.reset_all()
    yield system_mod.CodeCache
    UserManager.users.clear()
    UserManager.users.update(old_users)
    auth_rate_limiter.reset_all()


# ---------- 创建邀请码 ----------


@pytest.mark.asyncio
async def test_create_invite_code_rejects_existing(invite_env):
    # 用户配置中已存在的 code -> 400
    UserManager.users["alice"] = types.SimpleNamespace(  # type: ignore
        config=types.SimpleNamespace(user=types.SimpleNamespace(code="USED"))
    )
    r = await system_mod.create_invite_code(system_access=True, req=make_req("USED"))
    assert r.code == 400
    assert "邀请码已存在" in r.message

    # 缓存中已存在的 code -> 400
    await invite_env.set("CACHED", make_req("CACHED"))
    r2 = await system_mod.create_invite_code(system_access=True, req=make_req("CACHED"))
    assert r2.code == 400
    assert "邀请码已存在" in r2.message

    # 全新 code -> 200 并写入缓存
    r3 = await system_mod.create_invite_code(system_access=True, req=make_req("FRESH"))
    assert r3.code == 200
    assert r3.data == "FRESH"
    assert (await invite_env.get("FRESH")) is not None


@pytest.mark.asyncio
async def test_concurrent_create_same_code_only_one_succeeds(invite_env):
    # 并发创建同一 code：锁内双端检查 + 写入，只有一个成功
    r1, r2 = await asyncio.gather(
        system_mod.create_invite_code(system_access=True, req=make_req("RACE")),
        system_mod.create_invite_code(system_access=True, req=make_req("RACE")),
    )
    assert sorted([r1.code, r2.code]) == [200, 400]
    assert (await invite_env.get("RACE")) is not None


# ---------- 注册消费 ----------


@pytest.mark.asyncio
async def test_register_consumes_invite_code(invite_env):
    await invite_env.set("CODE1", make_req("CODE1"))
    r = await system_mod.register_user(
        req=system_mod.RegisterRequest(username="newuser1", password="Passw0rd!", code="CODE1"),
        ip="1.1.1.1",
    )
    assert r.code == 200
    # 邀请码已被消费删除
    assert (await invite_env.get("CODE1")) is None
    assert "newuser1" in UserManager.users


@pytest.mark.asyncio
async def test_concurrent_register_same_code_only_one_succeeds(invite_env):
    await invite_env.set("SHARED", make_req("SHARED"))

    r1, r2 = await asyncio.gather(
        system_mod.register_user(
            req=system_mod.RegisterRequest(username="newuser1", password="Passw0rd!", code="SHARED"),
            ip="2.2.2.2",
        ),
        system_mod.register_user(
            req=system_mod.RegisterRequest(username="newuser2", password="Passw0rd!", code="SHARED"),
            ip="2.2.2.2",
        ),
    )

    assert sorted([r1.code, r2.code]) == [200, 400]
    # 只创建一个用户，无重复用户
    assert set(UserManager.users) in ({"newuser1"}, {"newuser2"})
    # 邀请码已被消费删除，不可再次使用
    assert (await invite_env.get("SHARED")) is None

    r3 = await system_mod.register_user(
        req=system_mod.RegisterRequest(username="newuser3", password="Passw0rd!", code="SHARED"),
        ip="2.2.2.3",
    )
    assert r3.code == 400
