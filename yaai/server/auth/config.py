"""Auth configuration loaded from environment variables via Pydantic BaseSettings."""

import logging
import os
import secrets as _secrets

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _parse_comma_separated(v):
    """Parse a comma-separated string into a list, or pass through if already a list."""
    if isinstance(v, str):
        return [item.strip() for item in v.split(",") if item.strip()]
    return v


class JWTConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_JWT_", env_file=".env", extra="ignore")

    secret: SecretStr = SecretStr("")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30


class LocalAuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_LOCAL_", env_file=".env", extra="ignore")

    enabled: bool = True
    allow_registration: bool = False


class GoogleOAuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_OAUTH_GOOGLE_", env_file=".env", extra="ignore")

    enabled: bool = False
    client_id: SecretStr = SecretStr("")
    client_secret: SecretStr = SecretStr("")
    allowed_domains: list[str] = []
    auto_create_users: bool = True
    default_role: str = "viewer"
    owner_emails: list[str] = []
    viewer_emails: list[str] = []

    @field_validator("allowed_domains", "owner_emails", "viewer_emails", mode="before")
    @classmethod
    def parse_comma_separated(cls, v):
        return _parse_comma_separated(v)

    def resolve_role(self, email: str) -> str | None:
        """Return role for the email, or None if not in any list (access denied)."""
        lower = email.lower()
        if lower in {e.lower() for e in self.owner_emails}:
            return "owner"
        if lower in {e.lower() for e in self.viewer_emails}:
            return "viewer"
        return None


class OAuthConfig(BaseModel):
    google: GoogleOAuthConfig = Field(default_factory=GoogleOAuthConfig)


class GoogleSAConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_SERVICE_ACCOUNTS_GOOGLE_", env_file=".env", extra="ignore")

    enabled: bool = False
    allowed_emails: list[str] = []
    audience: str = ""

    @field_validator("allowed_emails", mode="before")
    @classmethod
    def parse_comma_separated(cls, v):
        return _parse_comma_separated(v)


class APIKeyServiceConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_SERVICE_ACCOUNTS_API_KEYS_", env_file=".env", extra="ignore")

    enabled: bool = True


class ServiceAccountsConfig(BaseModel):
    api_keys: APIKeyServiceConfig = Field(default_factory=APIKeyServiceConfig)
    google: GoogleSAConfig = Field(default_factory=GoogleSAConfig)


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", extra="ignore")

    enabled: bool = True
    default_admin_password: str = "changeme"
    jwt: JWTConfig = Field(default_factory=JWTConfig)
    local: LocalAuthConfig = Field(default_factory=LocalAuthConfig)
    oauth: OAuthConfig = Field(default_factory=OAuthConfig)
    service_accounts: ServiceAccountsConfig = Field(default_factory=ServiceAccountsConfig)


def load_auth_config() -> AuthConfig:
    """Load auth config from environment variables and .env file."""
    return AuthConfig()


_INSECURE_JWT_SECRETS = {"dev-secret-change-me", "changeme", "secret", ""}


def _is_production() -> bool:
    """Heuristic: production if ENVIRONMENT is set to 'production' or 'prod'."""
    env = os.environ.get("ENVIRONMENT", "development").lower()
    return env in ("production", "prod")


def _validate_jwt_secret(config: AuthConfig, is_prod: bool) -> None:
    """Validate the JWT secret configuration."""
    jwt_secret = config.jwt.secret.get_secret_value()
    if jwt_secret not in _INSECURE_JWT_SECRETS:
        return

    if is_prod:
        raise RuntimeError(
            "FATAL: JWT secret is insecure. Set AUTH_JWT_SECRET environment variable "
            "to a strong random value (e.g. openssl rand -base64 32)."
        )
    if jwt_secret == "":
        config.jwt.secret = SecretStr(_secrets.token_urlsafe(32))
        logger.warning(
            "AUTH_JWT_SECRET not configured — generated ephemeral secret. "
            "Sessions will NOT survive restarts. Set AUTH_JWT_SECRET for persistence."
        )
    else:
        logger.warning(
            "SECURITY WARNING: Using insecure default JWT secret. "
            "Set AUTH_JWT_SECRET environment variable for production."
        )


def validate_auth_config(config: AuthConfig) -> AuthConfig:
    """Validate auth config at startup. Logs warnings in dev, raises in production."""
    is_prod = _is_production()

    if not config.enabled:
        logger.info("Authentication is DISABLED — all endpoints are open")
        return config

    # --- Google OAuth: auto-disable local auth ---
    if config.oauth.google.enabled:
        if config.local.enabled:
            config.local.enabled = False
            logger.info("Google OAuth is enabled — local authentication auto-disabled")

    # --- Google OAuth: allowed_domains ---
    if config.oauth.google.enabled and not config.oauth.google.allowed_domains:
        if is_prod:
            raise RuntimeError(
                "FATAL: allowed_domains must be configured when Google OAuth is enabled. "
                "Without it, any Google account can log in. "
                "Set AUTH_OAUTH_GOOGLE_ALLOWED_DOMAINS."
            )
        logger.warning(
            "SECURITY WARNING: Google OAuth enabled without allowed_domains — "
            "any Google account can log in. Set AUTH_OAUTH_GOOGLE_ALLOWED_DOMAINS for production."
        )

    # --- Google SA: audience required ---
    if config.service_accounts.google.enabled and not config.service_accounts.google.audience:
        if is_prod:
            raise RuntimeError(
                "FATAL: audience must be configured when Google service account auth is enabled. "
                "ID token verification requires an audience to prevent token replay attacks. "
                "Set AUTH_SERVICE_ACCOUNTS_GOOGLE_AUDIENCE."
            )
        logger.warning(
            "SECURITY WARNING: Google SA auth enabled without audience — "
            "ID tokens will not be audience-checked. "
            "Set AUTH_SERVICE_ACCOUNTS_GOOGLE_AUDIENCE for production."
        )

    _validate_jwt_secret(config, is_prod)

    return config
