from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.constants import TRUSTED_PROXIES


class TrustedForwardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.client and request.client.host in TRUSTED_PROXIES:
            if forwarded_for := request.headers.get("X-Forwarded-For"):
                # X-Forwarded-For can be a comma-separated list of IPs.
                # The first one is the original client.
                client_ip = forwarded_for.split(",")[0].strip()
                request.scope["client"] = (client_ip, request.client.port)

        response = await call_next(request)
        return response
