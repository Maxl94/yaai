"""API key validation and Google Service Account ID token validation."""

import asyncio
import hashlib
import logging
from datetime import UTC, datetime

from cachetools import TTLCache
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yaai.server.auth.config import AuthConfig
from yaai.server.models.auth import APIKey, ServiceAccount

logger = logging.getLogger(__name__)

# Reusable transport for fetching Google's public signing keys.
_google_auth_request = GoogleAuthRequest()

# Cache verified results for 5 minutes, keyed by token hash.
_token_cache: TTLCache = TTLCache(maxsize=256, ttl=300)


def _token_cache_key(token: str) -> str:
    """Return a SHA-256 hex digest of the token for use as a cache key."""
    return hashlib.sha256(token.encode()).hexdigest()


def hash_api_key(raw_key: str) -> str:
    """Create a SHA-256 hash of an API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def validate_api_key(config: AuthConfig, key_value: str, db: AsyncSession) -> dict | None:
    """Validate an API key against the database.

    Returns a dict with identity info if valid, None otherwise.
    """
    if not config.service_accounts.api_keys.enabled:
        return None

    key_hash = hash_api_key(key_value)
    stmt = select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active.is_(True))
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    if api_key is None:
        return None

    # Check expiry
    if api_key.expires_at and api_key.expires_at < datetime.now(UTC):
        return None

    # Check service account is active (if linked)
    if api_key.service_account_id:
        sa_stmt = select(ServiceAccount).where(ServiceAccount.id == api_key.service_account_id)
        sa_result = await db.execute(sa_stmt)
        sa = sa_result.scalar_one_or_none()
        if sa is None or not sa.is_active:
            return None

    # Update last_used_at
    api_key.last_used_at = datetime.now(UTC)
    await db.commit()

    return {
        "identity_type": "api_key",
        "api_key_id": str(api_key.id),
        "service_account_id": str(api_key.service_account_id) if api_key.service_account_id else None,
    }


async def validate_google_sa_token(config: AuthConfig, token: str, db: AsyncSession) -> dict | None:
    """Validate a Google Service Account ID token via local JWT verification.

    Uses google.oauth2.id_token.verify_oauth2_token() to cryptographically
    verify the token signature against Google's public keys, check expiry,
    and validate the audience claim.

    Results are cached for 5 minutes keyed by a hash of the token.
    """
    if not config.service_accounts.google.enabled:
        return None

    # Check cache by token hash
    cache_key = _token_cache_key(token)
    cached = _token_cache.get(cache_key)
    if cached is not None:
        return cached

    # Determine audience (None if not configured — dev-mode only)
    audience = config.service_accounts.google.audience or None

    # verify_oauth2_token is synchronous (does JWT parsing + optional HTTP
    # to fetch Google certs on first call). Run in executor to avoid blocking
    # the async event loop on the cert-fetch cold path.
    loop = asyncio.get_running_loop()
    try:
        claims = await loop.run_in_executor(
            None,
            google_id_token.verify_oauth2_token,
            token,
            _google_auth_request,
            audience,
        )
    except ValueError as exc:
        logger.debug("Google SA ID token verification failed: %s", exc)
        return None

    email = claims.get("email")
    if not email:
        return None

    # Validate email is in allowed list
    if config.service_accounts.google.allowed_emails and email not in config.service_accounts.google.allowed_emails:
        return None

    # Look up the service account in the database by email
    stmt = select(ServiceAccount).where(ServiceAccount.google_sa_email == email)
    sa_result = await db.execute(stmt)
    sa = sa_result.scalar_one_or_none()
    if sa is None or not sa.is_active:
        return None

    result = {
        "identity_type": "google_sa",
        "email": email,
        "service_account_id": str(sa.id),
    }
    _token_cache[cache_key] = result
    return result
