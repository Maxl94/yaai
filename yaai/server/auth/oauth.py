"""Google OAuth2 flow using authlib."""

from authlib.integrations.starlette_client import OAuth

from yaai.server.auth.config import AuthConfig

_oauth: OAuth | None = None


def setup_oauth(config: AuthConfig) -> OAuth | None:
    """Initialize the OAuth client with Google provider if enabled."""
    global _oauth

    if not config.oauth.google.enabled:
        return None

    _oauth = OAuth()
    _oauth.register(
        name="google",
        client_id=config.oauth.google.client_id.get_secret_value(),
        client_secret=config.oauth.google.client_secret.get_secret_value(),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return _oauth


def get_oauth() -> OAuth | None:
    """Get the initialized OAuth client."""
    return _oauth
