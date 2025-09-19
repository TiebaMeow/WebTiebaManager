from __future__ import annotations

import asyncio
import json
import re
from enum import Enum
from typing import Literal, TypedDict
import io

import aiohttp
from pydantic import BaseModel
from fastapi.responses import StreamingResponse

from src.util.anonymous import AnonymousAiohttp
from src.util.logging import LOG_DIR, exception_logger, system_logger


class GetQrcodeResponse(TypedDict):
    imgurl: str
    errno: int
    sign: str
    prompt: str


class QrcodeData(BaseModel):
    imgurl: str = ""
    errno: int
    sign: str = ""
    prompt: str = ""


class ChannelVData(TypedDict):
    status: int
    v: str


class UnicastResponse(TypedDict):
    errno: Literal[-1, 0, 1, 2]
    channel_id: str
    channel_v: str


class QBErrorInfo(TypedDict):
    code: int
    msg: str


class QBSession(TypedDict):
    bduss: str
    stoken: str
    stokenList: str


class QBUser(TypedDict):
    username: str
    userId: str


class QBData(TypedDict):
    session: QBSession
    user: QBUser


class QrBdussLoginResponse(TypedDict):
    errInfo: QBErrorInfo
    data: QBData
    code: str


class QrcodeStatus(Enum):
    WAITING = "WAITING"  # 等待扫码
    SCANNED = "SCANNED"  # 已扫码，等待确认
    EXPIRED = "EXPIRED"  # 二维码过期
    FAILED = "FAILED"  # 登录失败
    SUCCESS = "SUCCESS"  # 登录成功


class AccountInfo(BaseModel):
    bduss: str
    stoken: str
    user_name: str


class QrcodeStatusData(BaseModel):
    status: QrcodeStatus
    account: AccountInfo | None = None


class TiebaQrcodeLogin:
    @classmethod
    async def get_login_qrcode(cls) -> QrcodeData | None:
        """
        获取登录二维码

        Returns:
            有效的二维码数据或None
        """
        with exception_logger("获取二维码失败", ignore_exceptions=(asyncio.TimeoutError, aiohttp.ClientError)):
            async with (await AnonymousAiohttp.session()).get(
                "https://passport.baidu.com/v2/api/getqrcode",
                params={"lp": "pc"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    system_logger.debug(f"获取二维码请求失败，状态码: {resp.status}")
                    return None

                text = await resp.text()
                try:
                    data: GetQrcodeResponse = json.loads(text)
                except json.JSONDecodeError:
                    file = LOG_DIR / "tieba.getqrcode.txt"
                    file.write_text(text, encoding="utf-8")
                    system_logger.warning(f"获取二维码返回非JSON数据，原始数据已保存至{file}")
                    return None

                system_logger.debug(f"获取二维码返回: {data}")

                if isinstance(data, dict):
                    try:
                        return QrcodeData.model_validate(data)
                    except Exception:
                        file = LOG_DIR / "tieba.getqrcode.txt"
                        file.write_text(text, encoding="utf-8")
                        system_logger.warning(f"获取二维码返回数据格式错误，原始数据已保存至{file}")

    @staticmethod
    def parse_stoken_list(stoken_list: str) -> str:
        """
        从百度stokenList中提取贴吧的stoken

        Args:
            stoken_list: stokenList字符串

        Returns:
            贴吧的stoken
        """
        result = {}
        correct_text = stoken_list.replace("&quot;", '"')
        for item in json.loads(correct_text):
            if "#" in item:
                key, value = item.split("#", 1)
                result[key] = value

        return result.get("tb", "")

    @classmethod
    async def get_login_result(cls, channel_v: str) -> QrcodeStatusData:
        """
        获取登录结果

        Args:
            channel_v: 二维码登录标识

        Returns:
            当前的二维码状态
        """
        with exception_logger("获取登录结果失败"):
            async with (await AnonymousAiohttp.session()).get(
                "https://passport.baidu.com/v3/login/main/qrbdusslogin", params={"bduss": channel_v}
            ) as resp:
                if resp.status != 200:
                    return QrcodeStatusData(status=QrcodeStatus.FAILED)

                text = await resp.text()
                try:
                    correct_text = re.sub(r"'([^']+)'", r'"\1"', text.replace("\\&", "&"))  # 将单引号改为双引号
                    data: QrBdussLoginResponse = json.loads(correct_text)
                    stoken = cls.parse_stoken_list(data["data"]["session"]["stokenList"])
                except json.JSONDecodeError:
                    file = LOG_DIR / "tieba.qrbdusslogin.txt"
                    file.write_text(text, encoding="utf-8")
                    system_logger.warning(f"获取二维码状态返回非JSON数据，原始数据已保存至{file}")
                    return QrcodeStatusData(status=QrcodeStatus.FAILED)

                system_logger.debug(f"获取登录结果返回: {data}")

                if data["code"] != "110000":
                    return QrcodeStatusData(status=QrcodeStatus.FAILED)

                return QrcodeStatusData(
                    status=QrcodeStatus.SUCCESS,
                    account=AccountInfo(
                        bduss=data["data"]["session"]["bduss"],
                        stoken=stoken,
                        user_name=data["data"]["user"]["username"],
                    ),
                )

        return QrcodeStatusData(status=QrcodeStatus.FAILED)

    @classmethod
    async def get_status(cls, sign: str) -> QrcodeStatusData:
        """
        获取二维码状态

        Args:
            sign: 二维码标识

        Returns:
            当前的二维码状态
        """
        with exception_logger("获取二维码状态失败"):
            async with (await AnonymousAiohttp.session()).get(
                "https://passport.baidu.com/channel/unicast", params={"channel_id": sign, "callback": ""}
            ) as resp:
                if resp.status != 200:
                    return QrcodeStatusData(status=QrcodeStatus.FAILED)

                text = await resp.text()
                try:
                    data: UnicastResponse = json.loads(text)
                except json.JSONDecodeError:
                    file = LOG_DIR / "tieba.unicast.txt"
                    file.write_text(text, encoding="utf-8")
                    system_logger.warning(f"获取二维码状态返回非JSON数据，原始数据已保存至{file}")
                    return QrcodeStatusData(status=QrcodeStatus.FAILED)

                system_logger.debug(f"获取二维码状态返回: {data}")

                if data["errno"] == -1:
                    return QrcodeStatusData(status=QrcodeStatus.EXPIRED)
                elif data["errno"] == 1:
                    return QrcodeStatusData(status=QrcodeStatus.WAITING)
                elif data["errno"] == 2:
                    return QrcodeStatusData(status=QrcodeStatus.SCANNED)
                elif data["errno"] != 0:
                    return QrcodeStatusData(status=QrcodeStatus.FAILED)

                channel_v_str = data["channel_v"]
                try:
                    channel_v: ChannelVData = json.loads(channel_v_str)
                except json.JSONDecodeError:
                    file = LOG_DIR / "tieba.channel_v.txt"
                    file.write_text(channel_v_str, encoding="utf-8")
                    system_logger.warning(f"获取二维码状态channel_v返回非JSON数据，原始数据已保存至{file}")
                    return QrcodeStatusData(status=QrcodeStatus.FAILED)

                if channel_v["status"] == 1:
                    return QrcodeStatusData(status=QrcodeStatus.SCANNED)
                elif channel_v["status"] == 2:
                    # 用户取消登录
                    return QrcodeStatusData(status=QrcodeStatus.EXPIRED)
                elif channel_v["status"] != 0:
                    return QrcodeStatusData(status=QrcodeStatus.EXPIRED)

                return await cls.get_login_result(channel_v["v"])

        return QrcodeStatusData(status=QrcodeStatus.FAILED)

    @classmethod
    async def qrcode_image(cls, sign: str):
        async with (await AnonymousAiohttp.session()).get(
            "https://passport.baidu.com/v2/api/qrcode",
            params={"lp": "pc", "sign": sign},
        ) as resp:
            image_data = await resp.read()
            return StreamingResponse(io.BytesIO(image_data), media_type="image/png")
