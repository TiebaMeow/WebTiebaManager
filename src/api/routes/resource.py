from __future__ import annotations

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Literal

import cv2
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.controller import Controller
from src.utils.anonymous import AnoymousTiebaMeow
from src.utils.logging import exception_logger

from ..auth import (
    RESOURCE_TOKEN_TTL,
    create_resource_access_token,
    current_user_depends,
    resource_access_depends,
)
from ..server import BaseResponse, app

if TYPE_CHECKING:
    import numpy as np


class ResourceTokenData(BaseModel):
    token: str
    expires_in: int


@app.post("/resources/token", tags=["resources"])
async def create_resource_token(user: current_user_depends) -> BaseResponse[ResourceTokenData]:
    """签发短时效、仅授权 /resources/* 读图 的专用资源 token（P1-4）。

    需要普通登录 token（Authorization: Bearer）认证；签发 scope=resources 的 HS256 JWT。
    """
    token = create_resource_access_token(user.username)
    return BaseResponse(data=ResourceTokenData(token=token, expires_in=RESOURCE_TOKEN_TTL))


class ResourceAPIExecutorManager:
    executor: ThreadPoolExecutor | None = None

    @classmethod
    def get_executor(cls) -> ThreadPoolExecutor:
        if cls.executor is None:
            cls.executor = ThreadPoolExecutor(max_workers=4)
        return cls.executor

    @classmethod
    async def shutdown_executor(cls, _: None = None) -> None:
        if cls.executor:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, cls.executor.shutdown, True)
            cls.executor = None


def ndarray2image(image: np.ndarray | None) -> io.BytesIO:
    if image is None or not image.any():
        image_bytes = b""
    else:
        image_bytes = cv2.imencode(".webp", image)[1].tobytes()

    return io.BytesIO(image_bytes)


@app.get("/resources/portrait/{portrait}", tags=["resources"])
async def get_portrait(
    portrait: str, size: Literal["s", "m", "l"] = "s", user: resource_access_depends = None
) -> StreamingResponse:  # noqa: ANN001
    if not Controller.running:
        raise HTTPException(status_code=503, detail="Service Unavailable")
    with exception_logger("获取头像失败"):
        image = await (await AnoymousTiebaMeow.client()).get_portrait(portrait, size=size)
    loop = asyncio.get_running_loop()
    return StreamingResponse(
        content=await loop.run_in_executor(ResourceAPIExecutorManager.get_executor(), ndarray2image, image.img),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/resources/image/{hash}", tags=["resources"])
async def get_image(
    hash: str, size: Literal["s", "m", "l"] = "s", user: resource_access_depends = None  # noqa: A002, ANN001
) -> StreamingResponse:
    if not Controller.running:
        raise HTTPException(status_code=503, detail="Service Unavailable")
    with exception_logger("获取图片失败"):
        image = await (await AnoymousTiebaMeow.client()).hash2image(hash, size=size)
    loop = asyncio.get_running_loop()
    return StreamingResponse(
        content=await loop.run_in_executor(ResourceAPIExecutorManager.get_executor(), ndarray2image, image.img),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )
