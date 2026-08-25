__all__ = [
    "parse_token",
    "current_user_depends",
    "system_access_depends",
    "ensure_system_access_depends",
    "ip_depends",
    "resource_access_depends",
    "create_resource_access_token",
    "RESOURCE_TOKEN_TTL",
]

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from typing import Annotated, Literal

import jwt
from fastapi import Depends, Form, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from src.core.controller import Controller
from src.user.manager import User, UserManager
from src.utils.logging import system_logger
from src.utils.rate_limit import auth_rate_limiter

from .encryt import encrypt
from .server import app

ALGORITHM = "HS256"

# 资源只读 token 默认有效期（秒）：15 分钟（P1-4，已确认固定常量）
RESOURCE_TOKEN_TTL = 15 * 60

# 登录失败统一延迟（秒）：叠加在认证失败路径上，使失败耗时趋于一致，
# 避免仅靠随机 sleep 造成仍可观测的账号存在性差异（P1-3）。
LOGIN_FAILURE_DELAY = 0.2

# 用户不存在时用于对齐校验路径的 dummy 存储哈希（P1-3）。
# 仅用于时序侧信道防护，不会匹配任何真实密码。
DUMMY_PASSWORD_HASH = "$2b$12$dummy.dummy.dummy.dummy.dummy.dummy.notmatch"


class AdvancedOAuth2RequestForm(OAuth2PasswordRequestForm):
    def __init__(
        self,
        username: str = Form(...),
        password: str = Form(...),
        key: str = Form(default=None),  # 新增参数
    ):
        super().__init__(username=username, password=password)
        self.key = key  # 存储额外参数


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")


class Token(BaseModel):
    access_token: str
    token_type: str
    system_access: bool


class TokenData(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password_last_update: int
    key_last_update: int | None

    def serialize(self):
        return {"sub": self.username, "pwd_iat": self.password_last_update, "key_iat": self.key_last_update}

    @classmethod
    def deserialize(cls, payload: dict):
        username = payload.get("sub")
        password_last_update = payload.get("pwd_iat")
        if not username or not password_last_update:
            return False
        return cls(username=username, password_last_update=password_last_update, key_last_update=payload.get("key_iat"))


def verify_password(plain_password: str, encrypted_password: str):
    return encrypt(plain_password) == encrypted_password


async def authenticate_user(username: str, password: str):
    user_expection = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的用户名或密码", headers={"WWW-Authenticate": "Bearer"}
    )
    user = UserManager.get_user(username)
    if user is None:
        # 用户不存在时也执行一次等价的密码校验路径，避免时序侧信道泄露账号存在性（P1-3）
        verify_password(password, DUMMY_PASSWORD_HASH)
        raise user_expection
    if not verify_password(password, user.config.user.password):
        raise user_expection

    return user


async def authenticate_system(key: str | None) -> bool:
    if not key:
        return False

    if not verify_password(key, Controller.config.server.key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="系统密钥错误", headers={"WWW-Authenticate": "Bearer"}
        )
    return True


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now() + expires_delta
    else:
        expire = datetime.now() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, Controller.config.server.secret_key, algorithm=ALGORITHM)
    return encoded_jwt


async def parse_token(token: Annotated[str, Depends(oauth2_scheme)]):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, Controller.config.server.secret_key, algorithms=[ALGORITHM])
        if not (data := TokenData.deserialize(payload)):
            raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception  # noqa: B904

    user = UserManager.get_user(data.username)
    if user is None or user.config.user.password_last_update != data.password_last_update:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if data.key_last_update:
        if data.key_last_update != Controller.config.server.key_last_update:
            raise credentials_exception
        system_access = True
    else:
        system_access = False

    return user, system_access


def create_resource_access_token(username: str, expires_delta: timedelta | None = None) -> str:
    """签发短时效、仅授权 /resources/* 读图的专用资源 token（scope=resources，P1-4）。

    复用现有 HS256 secret_key 签名，不新增密钥管理；claims 含 scope/exp/iat/sub。
    注意：iat/exp 使用 UTC 时间，避免 naive 本地时间导致 PyJWT iat 校验失败。
    """
    now = datetime.now(UTC)
    to_encode: dict = {"sub": username, "scope": "resources", "iat": now}
    if expires_delta:
        to_encode["exp"] = now + expires_delta
    else:
        to_encode["exp"] = now + timedelta(seconds=RESOURCE_TOKEN_TTL)
    return jwt.encode(to_encode, Controller.config.server.secret_key, algorithm=ALGORITHM)


async def get_resource_access(  # noqa: ANN201
    request: Request, token: str | None = Query(default=None)
):
    """供 GET /resources/* 使用的统一鉴权依赖。

    从 query `?token=` 或 `Authorization: Bearer` 读取资源 token；
    校验签名 + scope=="resources" + exp 未过 + sub 用户仍存在；失败 401。
    普通全权限 access token（无 resources scope）必须被拒绝。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    raw = token
    if not raw:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw = auth_header[7:]

    if not raw:
        raise credentials_exception

    try:
        payload = jwt.decode(raw, Controller.config.server.secret_key, algorithms=[ALGORITHM])
    except InvalidTokenError:
        raise credentials_exception  # noqa: B904

    if payload.get("scope") != "resources":
        # 全权限 access token 或无资源 scope 的 token 一律拒绝
        raise credentials_exception

    username = payload.get("sub")
    if not username:
        raise credentials_exception

    user = UserManager.get_user(username)
    if user is None:
        raise credentials_exception

    return user


resource_access_depends = Annotated[User, Depends(get_resource_access)]


async def get_current_user(data: Annotated[tuple[User, bool], Depends(parse_token)]):  # noqa: FURB118
    return data[0]


async def get_system_access(data: Annotated[tuple[User, bool], Depends(parse_token)]):  # noqa: FURB118
    return data[1]


async def ensure_system_access(system_access: Annotated[tuple[bool], Depends(get_system_access)]):
    if not system_access:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="系统访问权限不足",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return system_access


async def get_ip(request: Request):
    if request.client:
        return request.client.host
    else:
        return "unknown"


current_user_depends = Annotated[User, Depends(get_current_user)]
system_access_depends = Annotated[bool, Depends(get_system_access)]
ensure_system_access_depends = Annotated[bool, Depends(ensure_system_access)]
ip_depends = Annotated[str | None, Depends(get_ip)]


@app.post("/api/login", tags=["token"])
async def login_for_access_token(form_data: Annotated[AdvancedOAuth2RequestForm, Depends()], ip: ip_depends) -> Token:
    ip_key = ip or "unknown"
    if auth_rate_limiter.is_locked(ip_key):
        raise HTTPException(
            status_code=429, detail="登录失败次数过多，请稍后再试", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        user = await authenticate_user(form_data.username, form_data.password)
        system_access = await authenticate_system(form_data.key)
    except HTTPException as e:
        system_logger.warning(f"用户 {form_data.username} 登录失败 IP: {ip}")
        # 统一失败延迟：使失败耗时趋于一致，避免账号存在性时序侧信道（P1-3）
        await asyncio.sleep(LOGIN_FAILURE_DELAY)
        auth_rate_limiter.record_failure(ip_key)
        if auth_rate_limiter.is_locked(ip_key):
            raise HTTPException(
                status_code=429, detail="登录失败次数过多，请稍后再试", headers={"WWW-Authenticate": "Bearer"}
            ) from None
        raise e
    access_token_expires = timedelta(days=Controller.config.server.token_expire_days)
    access_token = create_access_token(
        data=TokenData(
            username=user.username,
            password_last_update=user.config.user.password_last_update,
            key_last_update=Controller.config.server.key_last_update if system_access else None,
        ).serialize(),
        expires_delta=access_token_expires,
    )
    system_logger.info(f"用户 {user.username} 登录成功 IP: {ip} 系统权限: {'是' if system_access else '否'}")
    # 登录成功后清除该 IP 的失败记录，正常用户不受限流影响（P1-3）
    auth_rate_limiter.clear(ip_key)
    return Token(access_token=access_token, token_type="bearer", system_access=system_access)
