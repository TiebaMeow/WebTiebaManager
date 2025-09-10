from typing import TYPE_CHECKING, Literal

import aiotieba

from src.config import write_config
from src.constance import USER_DIR
from src.control import Controller
from src.process.process import Processer
from src.process.typedef import ProcessObject
from src.rule.operation import OperationGroup
from src.rule.rule_set import RuleSet
from src.tieba.info import TiebaInfo
from src.typedef import Content
from src.util.tools import int_time

from .config import UserConfig
from .confirm import ConfirmCache, ConfirmData

if TYPE_CHECKING:
    from src.util.event import EventListener


class TiebaClientEmpty:
    class InvalidClientError(Exception):
        pass

    bduss = ""
    stoken = ""
    client = None  # type: ignore
    info = None  # type: ignore

    def __init__(self) -> None:
        pass

    async def delete(self, content: Content):
        raise self.InvalidClientError("invalid client")

    async def block(self, content: Content, day: int = 1, reason: str = ""):
        raise self.InvalidClientError("invalid client")

    async def delete_thread(self, fname: str, tid: int):
        raise self.InvalidClientError("invalid client")

    async def delete_post(self, fname: str, tid: int, pid: int):
        raise self.InvalidClientError("invalid client")


class TiebaClient:
    def __init__(self, bduss: str, stoken: str) -> None:
        self.bduss = bduss
        self.stoken = stoken
        self.client: aiotieba.Client = None  # type: ignore
        self.info: aiotieba.typing.UserInfo = None  # type: ignore

    @classmethod
    async def create(cls, bduss: str, stoken: str):
        client = cls(bduss, stoken)
        try:
            if not await client.start():
                return TiebaClientEmpty()
        except ValueError:
            # TODO bduss / stoken 长度错误，优化错误提示
            return TiebaClientEmpty()

        return client

    async def start(self) -> bool:
        self.client = aiotieba.Client(BDUSS=self.bduss, STOKEN=self.stoken)
        await self.client.__aenter__()
        self.info = await self.client.get_self_info()
        if self.info.user_id == 0:
            await self.stop()
            return False

        return True

    async def stop(self):
        if self.client:
            await self.client.__aexit__()

    async def delete_thread(self, fname: str, tid: int):
        return await self.client.del_thread(fname, tid=tid)

    async def delete_post(self, fname: str, tid: int, pid: int):
        return await self.client.del_post(fname, tid=tid, pid=pid)

    async def delete(self, content: Content):
        if content.type == "thread":
            return await self.delete_thread(content.fname, tid=content.tid)
        else:
            return await self.delete_post(content.fname, tid=content.tid, pid=content.pid)

    async def block(self, content: Content, day: int = 1, reason: str = ""):
        return await self.client.block(content.fname, content.user.user_id, day=day, reason=reason)


class User:
    CONFIG_FILE = "config.yaml"

    def __init__(self, config: UserConfig) -> None:
        """
        需调用update_config进行初始化
        """
        self.config = config
        self.listeners: list[EventListener] = [Controller.DispatchContent.on(self.process)]
        self.client: TiebaClient | TiebaClientEmpty = TiebaClientEmpty()
        self.dir = USER_DIR / self.config.user.username
        if not self.dir.exists():
            self.dir.mkdir(parents=True)

        self.confirm = ConfirmCache(self.dir, expire_time=self.config.process.confirm_expire)

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
        await user.update_config(config)
        return user

    async def stop(self, _: None = None):
        [i.un_register() for i in self.listeners]
        self.listeners.clear()

        if isinstance(self.client, TiebaClient):
            await self.client.stop()

        await self.confirm.stop()

    async def update_config(self, new_config: UserConfig):
        old_config = self.config
        self.config = new_config

        self.processer = Processer(new_config)
        if new_config.forum.login_ready and (
            new_config.forum.bduss != old_config.forum.bduss or new_config.forum.stoken != old_config.forum.stoken
        ):
            self.client = await TiebaClient.create(new_config.forum.bduss, new_config.forum.stoken)
            if isinstance(self.client, TiebaClientEmpty):
                # TODO 在这里添加登录失败提示
                pass
        else:
            self.client = TiebaClientEmpty()

        if old_config.process.confirm_expire != new_config.process.confirm_expire:
            await self.confirm.set_expire_time(new_config.process.confirm_expire)

        self.save_config()

    def save_config(self):
        write_config(self.config, self.dir / User.CONFIG_FILE)

    async def process(self, content: Content):
        obj = ProcessObject(content)
        result_rule_set = await self.processer.process(obj)
        if result_rule_set:
            await self.operate_rule_set(obj, result_rule_set)

    async def operate(self, obj: ProcessObject, og: OperationGroup):
        # TODO 日志
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
                            await self.client.delete_thread(obj.content.fname, obj.content.tid)
                            continue

                    await self.client.delete(obj.content)
                elif operation.type == "block":
                    await self.client.block(
                        obj.content,
                        operation.options.day or self.config.forum.block_day,
                        operation.options.reason or self.config.forum.block_reason,
                    )
                else:
                    # log不支持的处理
                    pass

    async def operate_rule_set(self, obj: ProcessObject, rule_set: RuleSet):
        """
        执行规则集的直接操作
        """
        if self.config.process.mandatory_confirm or rule_set.manual_confirm:
            if og := rule_set.operations.direct_operations:
                await self.operate(obj, og)

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

        else:
            try:
                await self.operate(obj, rule_set.operations)
            except TiebaClientEmpty.InvalidClientError:
                # TODO 登录失效提示
                pass

    async def operate_confirm(self, confirm: ConfirmData | str | int, action: Literal["execute", "ignore"]) -> bool:
        # TODO confirm日志显示
        if isinstance(confirm, (str, int)):
            if (_ := await self.confirm.get(confirm)) is None:
                return False

            confirm = _

        if isinstance(confirm, ConfirmData):
            if action == "ignore":
                await self.confirm.delete(confirm.content.pid)
                return True
            elif action == "execute":
                obj = ProcessObject(confirm.content, confirm.data)
                og = OperationGroup.deserialize(confirm.operations)  # type: ignore
                await self.operate(obj, og)
                await self.confirm.delete(confirm.content.pid)
                return True
            else:
                raise ValueError("Invalid action")
        else:
            raise ValueError("Invalid confirm type")
