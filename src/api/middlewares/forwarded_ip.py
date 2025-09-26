import ipaddress
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from src.core.constants import TRUSTED_PROXIES


def is_trusted_proxy(ip: str) -> bool:
    try:
        ip_addr = ipaddress.ip_address(ip)
        for proxy in TRUSTED_PROXIES:
            if "/" in proxy:
                if ip_addr in ipaddress.ip_network(proxy, strict=False):
                    return True
            else:
                if ip_addr == ipaddress.ip_address(proxy):
                    return True
    except ValueError:
        pass
    return False


class TrustedForwardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.client and is_trusted_proxy(request.client.host):
            if forwarded_for := request.headers.get("X-Forwarded-For"):
                # X-Forwarded-For can be a comma-separated list of IPs.
                # The first one is the original client.
                client_ip = forwarded_for.split(",")[0].strip()
                try:
                    ipaddress.ip_address(client_ip)
                    request.scope["client"] = (client_ip, request.client.port)
                except ValueError:
                    pass

        response = await call_next(request)
        return response
