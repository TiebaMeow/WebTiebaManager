from __future__ import annotations

from fastapi.responses import StreamingResponse  # noqa: TC002
from pydantic import BaseModel

from src.server import BaseResponse, app, current_user_depends
from src.tieba.qrcode import QrcodeData, QrcodeStatus, QrcodeStatusData, TiebaQrcodeLogin


@app.get("/api/tieba/get_qrcode", tags=["tieba"])
async def get_tieba_qrcode(user: current_user_depends) -> BaseResponse[QrcodeData | None]:
    """获取登录二维码"""
    data = await TiebaQrcodeLogin.get_login_qrcode()
    if data is None:
        return BaseResponse(data=None, message="获取二维码失败", code=500)

    if data.errno != 0:
        return BaseResponse(data=data, message="获取二维码失败", code=500)

    return BaseResponse(data=data)


class QrcodeStatusRequest(BaseModel):
    sign: str


@app.post("/api/tieba/qrcode_status", tags=["tieba"])
async def get_tieba_qrcode_status(
    req: QrcodeStatusRequest,
    user: current_user_depends,
) -> BaseResponse[QrcodeStatusData]:
    """获取二维码登录状态"""
    data = await TiebaQrcodeLogin.get_status(req.sign)
    if data is None:
        return BaseResponse(data=QrcodeStatusData(status=QrcodeStatus.FAILED), message="获取二维码状态出错", code=500)
    if data.status == QrcodeStatus.FAILED:
        return BaseResponse(data=data, message="获取二维码状态失败", code=500)

    return BaseResponse(data=data)


@app.get("/api/tieba/qrcode_image", tags=["tieba"])
async def get_tieba_qrcode_image(sign: str) -> StreamingResponse:
    """获取二维码图片"""
    return await TiebaQrcodeLogin.qrcode_image(sign[::-1])
