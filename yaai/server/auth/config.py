"""Auth configuration loaded from environment variables via Pydantic BaseSettings."""

import logging
import secrets as _secrets

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from yaai.server.config import is_production, settings

logger = logging.getLogger(__name__)


def _parse_comma_separated(v):
    """Parse a comma-separated string into a list, or pass through if already a list."""
    if isinstance(v, str):
        return [item.strip() for item in v.split(",") if item.strip()]
    return v


# Public OAuth client IDs of the gcloud CLI (`print-identity-token`) and ADC (`application-default login`)
GCLOUD_TOKEN_AUDIENCES = [
    "32555940559.apps.googleusercontent.com",
    "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com",
]


class JWTConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_JWT_", env_file=".env", extra="ignore")

    secret: SecretStr = SecretStr("")

    # Hardcoded — not configurable (reduces attack surface)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30


class LocalAuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_LOCAL_", env_file=".env", extra="ignore")

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
    # Extra accepted `aud` values for Google user ID tokens (SDK/CLI); client_id is always accepted
    token_audiences: list[str] = Field(default_factory=lambda: list(GCLOUD_TOKEN_AUDIENCES))

    @field_validator("allowed_domains", "owner_emails", "viewer_emails", "token_audiences", mode="before")
    @classmethod
    def parse_comma_separated(cls, v):
        return _parse_comma_separated(v)

    def accepted_token_audiences(self) -> list[str]:
        """Return all audiences accepted for Google user ID tokens."""
        client_id = self.client_id.get_secret_value()
        return [aud for aud in [client_id, *self.token_audiences] if aud]

    def resolve_role(self, email: str) -> str | None:
        """Return role for an email, preferring explicit lists and falling back to default_role."""
        lower = email.lower()
        if lower in {e.lower() for e in self.owner_emails}:
            return "owner"
        if lower in {e.lower() for e in self.viewer_emails}:
            return "viewer"
        if self.default_role in {"owner", "viewer"}:
            return self.default_role
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
    jwt: JWTConfig = Field(default_factory=JWTConfig)
    local: LocalAuthConfig = Field(default_factory=LocalAuthConfig)
    oauth: OAuthConfig = Field(default_factory=OAuthConfig)
    service_accounts: ServiceAccountsConfig = Field(default_factory=ServiceAccountsConfig)

    @property
    def local_enabled(self) -> bool:
        """Local auth is enabled when Google OAuth is NOT enabled."""
        return not self.oauth.google.enabled


def load_auth_config() -> AuthConfig:
    """Load auth config from environment variables and .env file."""
    return AuthConfig()


_INSECURE_JWT_SECRETS = {"dev-secret-change-me", "changeme", "secret", ""}


_is_production = is_production  # backward-compatible alias


def _validate_jwt_secret(config: AuthConfig, is_prod: bool) -> None:
    """Validate the JWT secret configuration."""
    jwt_secret = config.jwt.secret.get_secret_value()
    if jwt_secret not in _INSECURE_JWT_SECRETS:
        return

    if is_prod:
        raise RuntimeError(
            "FATAL: AUTH_JWT_SECRET must be set in production; multiple instances and restarts need a shared "
            "secret. Generate one with: openssl rand -base64 32"
        )

    config.jwt.secret = SecretStr(_secrets.token_urlsafe(32))
    logger.warning(
        "AUTH_JWT_SECRET not configured — generated ephemeral secret. "
        "Sessions will NOT survive restarts. Set AUTH_JWT_SECRET for persistence."
    )


def validate_auth_config(config: AuthConfig) -> AuthConfig:
    """Validate auth config at startup. Logs warnings in dev, raises in production."""
    is_prod = _is_production()

    if not config.enabled:
        logger.info("Authentication is DISABLED — all endpoints are open")
        return config

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

    # --- Google SA: default audience to BASE_URL ---
    if config.service_accounts.google.enabled and not config.service_accounts.google.audience:
        config.service_accounts.google.audience = settings.base_url
        logger.info(
            "AUTH_SERVICE_ACCOUNTS_GOOGLE_AUDIENCE not set — defaulting to BASE_URL (%s)",
            settings.base_url,
        )

    _validate_jwt_secret(config, is_prod)

    return config
