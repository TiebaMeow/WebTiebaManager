from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import aiotieba

from src.config import write_config
from src.constance import USER_DIR
from src.control import Controller
from src.process.process import Processer
from src.process.typedef import ProcessObject
from src.rule.operation import OperationGroup
from src.tieba.info import TiebaInfo
from src.util.logging import logger
from src.util.tools import int_time

from .confirm import ConfirmCache, ConfirmData

if TYPE_CHECKING:
    from loguru import Logger

    from src.rule.rule_set import RuleSet
    from src.typedef import Content
    from src.util.event import EventListener

    from .config import UserConfig


class TiebaClientEmpty:
    class InvalidClientError(Exception):
        pass

    bduss = ""
    stoken = ""
    client = None  # type: ignore
    info = None  # type: ignore

    def __init__(self, logger: Logger) -> None:
        self.logger = logger

    async def delete(self, content: Content):
        raise self.InvalidClientError("无效的客户端")

    async def block(self, content: Content, day: int = 1, reason: str = ""):
        raise self.InvalidClientError("无效的客户端")

    async def delete_thread(self, fname: str, tid: int):
        raise self.InvalidClientError("无效的客户端")

    async def delete_post(self, fname: str, tid: int, pid: int):
        raise self.InvalidClientError("无效的客户端")


class TiebaClient:
    def __init__(self, bduss: str, stoken: str, logger: Logger) -> None:
        self.bduss = bduss
        self.stoken = stoken
        self.client: aiotieba.Client = None  # type: ignore
        self.info: aiotieba.typing.UserInfo = None  # type: ignore
        self.logger = logger

    @classmethod
    async def create(cls, bduss: str, stoken: str, logger: Logger):
        client = cls(bduss, stoken, logger)
        try:
            if not await client.start():
                logger.warning("登录失败，请检查 BDUSS 和 STOKEN 是否正确")
                return TiebaClientEmpty(logger)
        except ValueError:
            logger.warning("登录失败，请检查 BDUSS 和 STOKEN 是否正确")
            return TiebaClientEmpty(logger)

        return client

    async def start(self) -> bool:
        self.client = aiotieba.Client(BDUSS=self.bduss, STOKEN=self.stoken)
        await self.client.__aenter__()
        self.info = await self.client.get_self_info()
        if self.info.user_id == 0:
            await self.stop()
            return False

        self.logger.info(f"已登录，用户名：{self.info.user_name}")
        return True

    async def stop(self):
        if self.client:
            await self.client.__aexit__()

    async def _delete_thread(self, fname: str, tid: int):
        return await self.client.del_thread(fname, tid=tid)

    async def _delete_post(self, fname: str, tid: int, pid: int):
        return await self.client.del_post(fname, tid=tid, pid=pid)

    async def delete(self, content: Content):
        self.logger.info(f"正在删除 {content.mark}", tid=content.tid, pid=content.pid)
        if content.type == "thread":
            result = await self._delete_thread(content.fname, tid=content.tid)
        else:
            result = await self._delete_post(content.fname, tid=content.tid, pid=content.pid)

        if not result:
            self.logger.warning(f"删除失败 {content.mark} {result.err}", tid=content.tid, pid=content.pid)
            return False

        return True

    async def block(self, content: Content, day: int = 1, reason: str = ""):
        self.logger.info(f"正在封禁 {content.user.log_name}", uid=content.user.user_id)
        result = await self.client.block(content.fname, content.user.user_id, day=day, reason=reason)
        if not result:
            self.logger.warning(f"封禁失败 {content.user.log_name} {result.err}", uid=content.user.user_id)
            return False

        return True


class User:
    CONFIG_FILE = "config.yaml"

    def __init__(self, config: UserConfig) -> None:
        """
        需调用update_config进行初始化
        """
        self.config = config
        self.listeners: list[EventListener] = [Controller.DispatchContent.on(self.process)]
        self.dir = USER_DIR / self.config.user.username
        if not self.dir.exists():
            self.dir.mkdir(parents=True)

        self.processer = Processer(config)
        self.confirm = ConfirmCache(self.dir, expire_time=self.config.process.confirm_expire)
        self.logger = logger.bind(name=f"user.{self.config.user.username}")
        self.client: TiebaClient | TiebaClientEmpty = TiebaClientEmpty(self.logger)

    @property
    def enable(self):
        return self.config.enable

    @property
    def username(self):
        return self.config.user.username

    @property
    def fname(self) -> str:
        return self.config.forum.fname

    @classmethod
    async def create(cls, config: UserConfig):
        user = cls(config)
        await user.update_config(config, initialize=True)
        user.logger.info("初始化完成")
        return user

    async def stop(self, _: None = None):
        [i.un_register() for i in self.listeners]
        self.listeners.clear()

        if isinstance(self.client, TiebaClient):
            await self.client.stop()

        await self.confirm.stop()
        self.logger.info("停止运行")

    async def update_config(self, new_config: UserConfig, initialize: bool = False):
        if self.config == new_config and not initialize:
            return

        old_config = self.config
        self.config = new_config

        self.processer = Processer(new_config)
        if new_config.forum.login_ready and (
            new_config.forum.bduss != old_config.forum.bduss
            or new_config.forum.stoken != old_config.forum.stoken
            or initialize
        ):
            self.client = await TiebaClient.create(new_config.forum.bduss, new_config.forum.stoken, self.logger)
        else:
            self.client = TiebaClientEmpty(self.logger)

        if old_config.process.confirm_expire != new_config.process.confirm_expire:
            await self.confirm.set_expire_time(new_config.process.confirm_expire)

        if not initialize:
            self.save_config()
            self.logger.info("设置已更新")

    def save_config(self):
        write_config(self.config, self.dir / User.CONFIG_FILE)

    async def process(self, content: Content):
        obj = ProcessObject(content)
        result_rule_set = await self.processer.process(obj)
        if result_rule_set:
            self.logger.info(
                f"{content.mark} 命中 {result_rule_set.name}",
                tid=content.tid,
                pid=content.pid,
                uid=content.user.user_id,
            )
            await self.operate_rule_set(obj, result_rule_set)

    async def operate(self, obj: ProcessObject, og: OperationGroup):
        operations = og.operations
        if isinstance(operations, str):
            if operations == "ignore":
                return
            elif operations == "delete":
                await self.client.delete(obj.content)
            elif operations == "block":
                await self.client.block(
                    obj.content,
                    self.config.forum.block_day,
                    self.config.forum.block_reason,
                )
            elif operations == "delete_and_block":
                await self.client.delete(obj.content)
                await self.client.block(
                    obj.content,
                    self.config.forum.block_day,
                    self.config.forum.block_reason,
                )
            else:
                raise ValueError(f"Unknown operation: {operations}")
        else:
            for operation in operations:
                if operation.type == "delete":
                    if operation.options.delete_thread_if_author:
                        if await TiebaInfo.get_if_thread_author(obj):
                            await self.client.delete(obj.content)
                            continue

                    await self.client.delete(obj.content)
                elif operation.type == "block":
                    await self.client.block(
                        obj.content,
                        operation.options.day or self.config.forum.block_day,
                        operation.options.reason or self.config.forum.block_reason,
                    )
                else:
                    self.logger.warning(f"未知操作：{operation.type}")

    async def operate_rule_set(self, obj: ProcessObject, rule_set: RuleSet):
        """
        执行规则集的直接操作
        """
        if self.config.process.mandatory_confirm or rule_set.manual_confirm:
            if og := rule_set.operations.direct_operations:
                try:
                    await self.operate(obj, og)
                except TiebaClientEmpty.InvalidClientError:
                    self.logger.warning("操作失败，未登录")
                    return

            og = rule_set.operations.no_direct_operations

            if og:
                data = {}

                if not isinstance(og.operations, str):
                    for operation in og.operations:
                        # 储存operation需要的数据
                        await operation.store_data(obj, data)

                await self.confirm.set(
                    obj.content.pid,
                    ConfirmData(
                        content=obj.content,
                        data=data,
                        operations=og.serialize(),
                        process_time=int_time(),
                        rule_set_name=rule_set.name,
                    ),
                )

                self.logger.info(f"{obj.content.mark} 需要确认后才能继续操作", tid=obj.content.tid, pid=obj.content.pid)

        else:
            try:
                await self.operate(obj, rule_set.operations)
            except TiebaClientEmpty.InvalidClientError:
                self.logger.warning("操作失败，未登录")

    async def operate_confirm(self, confirm: ConfirmData | str | int, action: Literal["execute", "ignore"]) -> bool:
        if isinstance(confirm, (str, int)):
            if (_ := await self.confirm.get(confirm)) is None:
                self.logger.warning(f"未找到对应的确认请求 confirm={confirm}")
                return False

            confirm = _

        if isinstance(confirm, ConfirmData):
            if action == "ignore":
                await self.confirm.delete(confirm.content.pid)
                self.logger.info(
                    f"忽略 {confirm.content.mark} 的确认", tid=confirm.content.tid, pid=confirm.content.pid
                )
                return True
            elif action == "execute":
                obj = ProcessObject(confirm.content, confirm.data)
                og = OperationGroup.deserialize(confirm.operations)  # type: ignore
                self.logger.info(
                    f"执行 {confirm.content.mark} 的确认", tid=confirm.content.tid, pid=confirm.content.pid
                )
                await self.operate(obj, og)
                await self.confirm.delete(confirm.content.pid)
                return True
            else:
                self.logger.warning(f"未知的操作类型 {action}")
                raise ValueError("Invalid action")
        else:
            self.logger.warning(f"未知的确认类型 {type(confirm)}")
            raise ValueError("Invalid confirm type")
