"""Rate limiting configuration using slowapi."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def get_client_key(request: Request) -> str:
    """Return the rate-limit key (client IP) for a request.

    With RATE_LIMIT_TRUSTED_PROXY_HOPS=N (N > 0) the client IP is taken from the N-th entry from the
    right of X-Forwarded-For. Proxies append to that header, so only the rightmost N entries are
    trustworthy; anything further left is client-controlled and ignored. Falls back to the socket
    peer address when the header is missing or has fewer entries than expected.
    """
    try:
        hops = int(os.environ.get("RATE_LIMIT_TRUSTED_PROXY_HOPS", "0"))
    except ValueError:
        hops = 0
    if hops > 0:
        forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return get_remote_address(request)


limiter = Limiter(key_func=get_client_key, storage_uri=os.environ.get("RATE_LIMIT_STORAGE_URI") or "memory://")

if os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "false":
    limiter.enabled = False
