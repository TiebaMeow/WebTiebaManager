import aiohttp
import aiotieba


class AnonymousAiohttp:
    _session: aiohttp.ClientSession | None = None

    @classmethod
    async def session(cls):
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession()
            await cls._session.__aenter__()
        return cls._session

    @classmethod
    async def stop(cls, _=None):
        if cls._session and not cls._session.closed:
            await cls._session.__aexit__(None, None, None)
            cls._session = None


class AnonymousAiotieba:
    _client: aiotieba.Client | None = None

    @classmethod
    async def client(cls):
        if not cls._client:
            cls._client = aiotieba.Client()
            await cls._client.__aenter__()
        return cls._client

    @classmethod
    async def stop(cls, _=None):
        if cls._client:
            await cls._client.__aexit__()
            cls._client = None


async def stop_anonymous_clients(_=None):
    await AnonymousAiohttp.stop()
    await AnonymousAiotieba.stop()
