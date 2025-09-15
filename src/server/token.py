__all__ = [
    "parse_token",
    "current_user_depends",
    "system_access_depends",
    "ensure_system_access_depends",
    "ip_depends",
]

from datetime import datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Form, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel

from src.control import Controller
from src.user.manager import User, UserManager
from src.util.logging import system_logger

from .encryt import encrypt
from .server import app

ALGORITHM = "HS256"


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
    username: str
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
    if not (user := UserManager.get_user(username)):
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
    try:
        user = await authenticate_user(form_data.username, form_data.password)
        system_access = await authenticate_system(form_data.key)
    except HTTPException as e:
        system_logger.warning(f"用户 {form_data.username} 登录失败 IP: {ip}")
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
    return Token(access_token=access_token, token_type="bearer", system_access=system_access)
