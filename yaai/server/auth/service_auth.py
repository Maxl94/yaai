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
from yaai.server.models.auth import APIKey, AuthProvider, ServiceAccount, User, UserRole

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
    allowed = config.service_accounts.google.allowed_emails
    if not email or (allowed and email not in allowed):
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


# Cache for user ID token validations (5 min TTL)
_user_token_cache: TTLCache = TTLCache(maxsize=256, ttl=300)


async def validate_google_user_token(config: AuthConfig, token: str, db: AsyncSession) -> dict | None:
    """Validate a Google ID token and match against the User table.

    This allows users who authenticated via Google OAuth to also use
    the SDK/CLI with ``gcloud auth print-identity-token``.  The token
    is cryptographically verified the same way as SA tokens, but the
    email is looked up in the *users* table instead of *service_accounts*.
    """
    if not config.oauth.google.enabled:
        return None

    cache_key = _token_cache_key(token)
    cached = _user_token_cache.get(cache_key)
    if cached is not None:
        return cached

    # User ID tokens from `gcloud auth print-identity-token` have Google's
    # own OAuth client ID as audience (not the server URL), so we must
    # skip audience validation.  Security comes from the email being in
    # the User table + the token being cryptographically signed by Google.
    loop = asyncio.get_running_loop()
    try:
        claims = await loop.run_in_executor(
            None,
            google_id_token.verify_oauth2_token,
            token,
            _google_auth_request,
            None,  # no audience check for user tokens
        )
    except ValueError as exc:
        logger.debug("Google user ID token verification failed: %s", exc)
        return None

    email = claims.get("email")
    role = config.oauth.google.resolve_role(email) if email else None
    if not role:
        if email:
            logger.debug("Google user ID token email %s not authorized", email)
        return None

    # Look up user by email
    stmt = select(User).where(User.email == email, User.is_active.is_(True))
    user_result = await db.execute(stmt)
    user = user_result.scalar_one_or_none()

    # Auto-create user if enabled (mirrors browser OAuth auto_create_users)
    if user is None and config.oauth.google.auto_create_users:
        google_sub = claims.get("sub", "")
        username = claims.get("name") or email.split("@", maxsplit=1)[0]
        user = User(
            username=username,
            email=email,
            role=UserRole(role),
            auth_provider=AuthProvider.GOOGLE,
            google_sub=google_sub,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        logger.info("Auto-created user %s (%s) via Google ID token", username, email)

    if user is None:
        logger.debug("No active user found for email %s (auto_create disabled)", email)
        return None

    result = {
        "identity_type": "google_user",
        "user_id": str(user.id),
        "email": email,
        "role": str(user.role),
    }
    _user_token_cache[cache_key] = result
    return result
