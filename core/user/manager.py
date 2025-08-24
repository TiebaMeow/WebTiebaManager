import shutil

from core.constance import USER_DIR
from .user import User, UserConfig
from core.config import read_config, write_config
from core.control import Controller
from core.util.event import AsyncEvent


class UserManager:
    users: dict[str, User] = {}

    UserConfigChange = AsyncEvent[UserConfig]()
    UserChange = AsyncEvent[None]()

    @classmethod
    async def load_users(cls, _: None = None):
        for user_dir in USER_DIR.iterdir():
            if not user_dir.is_dir():
                continue

            user_config_path = user_dir / "config.yaml"
            if not user_config_path.exists():
                raise Exception(f"User config file not found for user {user_dir.stem}")

            user_config = read_config(user_config_path, UserConfig)
            if user_config.user.username != user_dir.stem:
                raise Exception(f"Username mismatch for user {user_dir.stem}")

            cls.users[user_config.user.username] = await User.create(user_config)
        
        await cls.UserChange.broadcast(None)

    @classmethod
    async def new_user(cls, config: UserConfig):
        if config.user.username in cls.users:
            raise ValueError(f"User {config.user.username} already exists")

        user = await User.create(config)
        cls.users[config.user.username] = user

        write_config(config, user.dir / "config.yaml")

    @classmethod
    async def delete_user(cls, username: str):
        if not username in cls.users:
            raise ValueError(f"User {username} does not exist")

        user = cls.users[username]
        shutil.rmtree(user.dir)

        await cls.UserChange.broadcast(None)

    @classmethod
    async def update_config(cls, config: UserConfig):
        if config.user.username not in cls.users:
            raise ValueError(f"User {config.user.username} does not exist")

        await cls.users[config.user.username].update_config(config)


Controller.Start.on(UserManager.load_users)
