from __future__ import annotations

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Literal

import cv2
from fastapi.responses import StreamingResponse

from src.utils.anonymous import AnonymousAiotieba

from ..server import app

if TYPE_CHECKING:
    import numpy as np


_executor = ThreadPoolExecutor(max_workers=4)


def ndarray2image(image: np.ndarray | None) -> io.BytesIO:
    if image is None or not image.any():
        image_bytes = b""
    else:
        image_bytes = cv2.imencode(".webp", image)[1].tobytes()

    return io.BytesIO(image_bytes)


@app.get("/resources/portrait/{portrait}", tags=["resources"])
async def get_portrait(portrait: str, size: Literal["s", "m", "l"] = "s") -> StreamingResponse:
    image = await (await AnonymousAiotieba.client()).get_portrait(portrait, size=size)
    loop = asyncio.get_running_loop()
    return StreamingResponse(
        content=await loop.run_in_executor(_executor, ndarray2image, image.img),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/resources/image/{hash}", tags=["resources"])
async def get_image(hash: str, size: Literal["s", "m", "l"] = "s") -> StreamingResponse:  # noqa: A002
    image = await (await AnonymousAiotieba.client()).hash2image(hash, size=size)
    loop = asyncio.get_running_loop()
    return StreamingResponse(
        content=await loop.run_in_executor(_executor, ndarray2image, image.img),
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )
