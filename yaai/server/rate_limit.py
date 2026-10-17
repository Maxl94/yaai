"""Rate limiting configuration using slowapi."""

import ipaddress
import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from yaai.server.config import env_bool


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def get_client_key(request: Request) -> str:
    """Return the rate-limit key (client IP) for a request.

    With RATE_LIMIT_TRUSTED_PROXY_HOPS=N (N > 0) the client IP is taken from the N-th entry from the
    right of X-Forwarded-For. Proxies append to that header, so only the rightmost N entries are
    trustworthy; anything further left is client-controlled and ignored. Falls back to the socket
    peer address when the header is missing, has fewer entries than expected or the selected entry
    is not a valid IP address. Multiple X-Forwarded-For header lines are treated as one list.
    """
    try:
        hops = int(os.environ.get("RATE_LIMIT_TRUSTED_PROXY_HOPS", "0"))
    except ValueError:
        hops = 0
    if hops > 0:
        header_value = ",".join(request.headers.getlist("x-forwarded-for"))
        forwarded = [part.strip() for part in header_value.split(",") if part.strip()]
        if len(forwarded) >= hops and _is_ip_address(forwarded[-hops]):
            return forwarded[-hops]
    return get_remote_address(request)


limiter = Limiter(key_func=get_client_key, storage_uri=os.environ.get("RATE_LIMIT_STORAGE_URI") or "memory://")

limiter.enabled = env_bool("RATE_LIMIT_ENABLED", True)
