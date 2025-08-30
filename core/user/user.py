from typing import TYPE_CHECKING, Literal

import aiotieba

from core.constance import USER_DIR
from core.control import Controller
from core.process.process import Processer
from core.process.typedef import ProcessObject
from core.rule.operation import OperationGroup
from core.rule.rule_set import RuleSet
from core.typedef import Content
from core.util.tools import int_time

from .config import UserConfig
from .confirm import ConfirmCache, ConfirmData

if TYPE_CHECKING:
    from core.util.event import EventListener


class TiebaClientEmpty:
    def __init__(self) -> None:
        pass

    async def delete(self, content: Content):
        raise Exception("invalid client")

    async def block(self, content: Content, day: int = 1, reason: str = ""):
        raise Exception("invalid client")


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

    async def delete(self, content: Content):
        if content.type == "Thread":
            return await self.client.del_thread(content.fname, tid=content.tid)
        else:
            return await self.client.del_post(content.fname, tid=content.tid, pid=content.pid)

    async def block(self, content: Content, day: int = 1, reason: str = ""):
        return await self.client.block(content.fname, content.user.user_id, day=day, reason=reason)


class User:
    def __init__(self, config: UserConfig) -> None:
        """
        需调用update_config进行初始化
        """
        self.config = config
        self.listeners: list[EventListener] = [
            Controller.DispatchContent.on(self.process),
            Controller.Stop.on(self.stop),
        ]
        self.client: TiebaClient | TiebaClientEmpty = TiebaClientEmpty()
        self.dir = USER_DIR / self.config.user.username
        if not self.dir.exists():
            self.dir.mkdir(parents=True)

        self.confirm = ConfirmCache(self.dir)

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

    async def update_config(self, config: UserConfig):
        # TODO 判断输入的bduss, stoken是否有效（是否被马赛克）
        self.config = config
        self.processer = Processer(config)
        if self.config.forum.login_ready:
            self.client = await TiebaClient.create(self.config.forum.bduss, self.config.forum.stoken)
            if isinstance(self.client, TiebaClientEmpty):
                # TODO 在这里添加登录失败提示
                pass
        else:
            self.client = TiebaClientEmpty()

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
                if operation.type == "Delete":
                    await self.client.delete(obj.content)
                elif operation.type == "Block":
                    await self.client.block(
                        obj.content,
                        operation.options.day or self.config.forum.block_day,
                        operation.options.reason or self.config.forum.block_reason,
                    )
                elif operation.type == "AuthorDelete":
                    # TODO db查询，完成功能适配
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
                self.confirm.set(
                    obj.content.pid,
                    ConfirmData(
                        content=obj.content,
                        data={},
                        operations=og.serialize(),
                        process_time=int_time(),
                        rule_set_name=rule_set.name,
                    ),
                )

        else:
            await self.operate(obj, rule_set.operations)

    async def operate_confirm(self, confirm: ConfirmData | str | int, action: Literal["execute", "ignore"]) -> bool:
        # TODO confirm日志显示
        if isinstance(confirm, (str, int)):
            if (_ := self.confirm.get(confirm)) is None:
                return False

            confirm = _

        if isinstance(confirm, ConfirmData):
            if action == "ignore":
                self.confirm.delete(confirm.content.pid)
                return True
            elif action == "execute":
                obj = ProcessObject(confirm.content, confirm.data)
                og = OperationGroup.deserialize(confirm.operations)  # type: ignore
                await self.operate(obj, og)
                return True
            else:
                raise ValueError("Invalid action")
        else:
            raise ValueError("Invalid confirm type")
