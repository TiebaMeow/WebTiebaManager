import shutil

from core.config import read_config, write_config
from core.constance import USER_DIR
from core.control import Controller
from core.util.event import AsyncEvent

from .user import User, UserConfig


class UserManager:
    users: dict[str, User] = {}

    UserConfigChange = AsyncEvent[UserConfig]()
    UserChange = AsyncEvent[None]()

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
                raise ValueError(f"User {config.user.username} already exists")

        user = await User.create(config)
        cls.users[config.user.username] = user

        write_config(config, user.dir / User.CONFIG_FILE)

    @classmethod
    async def delete_user(cls, username: str):
        if username not in cls.users:
            raise ValueError(f"User {username} does not exist")

        user = cls.users[username]
        shutil.rmtree(user.dir)

        await cls.UserChange.broadcast(None)

    @classmethod
    async def update_config(cls, config: UserConfig):
        if config.user.username not in cls.users:
            raise ValueError(f"User {config.user.username} does not exist")

        await cls.users[config.user.username].update_config(config)
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
        return True

    @classmethod
    async def enable_user(cls, username: str):
        return await cls.change_user_status(username, True)

    @classmethod
    async def disable_user(cls, username: str):
        return await cls.change_user_status(username, False)


Controller.Start.on(UserManager.load_users)
Controller.Stop.on(UserManager.clear_users)
