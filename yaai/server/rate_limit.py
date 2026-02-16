"""Rate limiting configuration using slowapi."""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

if os.environ.get("RATE_LIMIT_ENABLED", "true").lower() == "false":
    limiter.enabled = False
