from __future__ import annotations

import shutil

from src.util.config import read_config, write_config
from src.constance import USER_DIR
from src.control import Controller
from src.util.event import AsyncEvent
from src.util.logging import system_logger

from .config import UserConfig
from .user import User


class UserManager:
    users: dict[str, User] = {}

    UserConfigChange = AsyncEvent[UserConfig]()
    UserChange = AsyncEvent[None]()

    @classmethod
    def get_valid_usernames(cls) -> list[str]:
        """
        用于检测是否有有效的用户

        Returns:
            list[str]: 有效用户名列表
        """
        if cls.users:
            return list(cls.users.keys())

        usernames = []

        for userdir in USER_DIR.iterdir():
            if not userdir.is_dir():
                continue

            user_config_path = userdir / User.CONFIG_FILE
            if not user_config_path.exists():
                continue

            try:
                user_config = read_config(user_config_path, UserConfig)
            except Exception:
                continue
            if user_config.user.username != userdir.stem:
                continue

            usernames.append(user_config.user.username)

        return usernames

    @classmethod
    async def silent_load_users(cls):
        await cls.clear_users()

        for user_dir in USER_DIR.iterdir():
            if not user_dir.is_dir():
                continue

            user_config_path = user_dir / User.CONFIG_FILE
            if not user_config_path.exists():
                raise Exception(f"User config file not found for user {user_dir.stem}")

            user_config = read_config(user_config_path, UserConfig)
            if user_config.user.username != user_dir.stem:
                raise Exception(f"Username mismatch for user {user_dir.stem}")

            cls.users[user_config.user.username] = await User.create(user_config)

    @classmethod
    async def load_users(cls, _: None = None):
        await cls.silent_load_users()
        await cls.UserChange.broadcast(None)
        system_logger.info(f"加载 {len(cls.users)} 个用户")

    @classmethod
    async def clear_users(cls, _: None = None):
        for user in cls.users.values():
            await user.stop()

        cls.users.clear()

    @classmethod
    async def new_user(cls, config: UserConfig, force: bool = False):
        if config.user.username in cls.users:
            if force:
                shutil.rmtree(cls.users[config.user.username].dir)
                cls.users.pop(config.user.username)
            else:
                raise ValueError(f"用户 {config.user.username} 已存在")

        user = await User.create(config)
        cls.users[config.user.username] = user

        write_config(config, user.dir / User.CONFIG_FILE)

        system_logger.info(f"创建用户 {config.user.username}")

    @classmethod
    async def delete_user(cls, username: str):
        if username not in cls.users:
            raise ValueError(f"用户 {username} 不存在")

        user = cls.users[username]
        await user.delete()
        cls.users.pop(username)

        await cls.UserChange.broadcast(None)

        system_logger.info(f"删除用户 {username}")

    @classmethod
    async def update_config(cls, config: UserConfig, /, system_access: bool = False):
        if config.user.username not in cls.users:
            raise ValueError(f"用户 {config.user.username} 不存在")

        await cls.users[config.user.username].update_config(config, system_access=system_access)
        await cls.UserConfigChange.broadcast(config)

    @classmethod
    def get_user(cls, username: str):
        return cls.users.get(username)

    @classmethod
    async def change_user_status(cls, username: str, status: bool):
        user = cls.get_user(username)
        if not user:
            return False
        if user.config.enable == status:
            return True

        new_config = user.config.model_copy(deep=True)
        new_config.enable = status
        await cls.update_config(new_config)

        system_logger.info(f"{'启用' if status else '禁用'}用户 {username}")
        user.logger.info(f"已{'启用' if status else '禁用'}")

        return True

    @classmethod
    async def enable_user(cls, username: str):
        return await cls.change_user_status(username, True)

    @classmethod
    async def disable_user(cls, username: str):
        return await cls.change_user_status(username, False)


Controller.Start.on(UserManager.load_users)
Controller.Stop.on(UserManager.clear_users)
