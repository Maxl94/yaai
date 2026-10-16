"""Security response headers (CSP, HSTS, clickjacking and MIME-sniffing protection)."""

import os

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Vite emits external module scripts only; Vuetify needs inline styles; ECharts renders to canvas.
SPA_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)

# Swagger UI / ReDoc load assets from cdn.jsdelivr.net and run an inline bootstrap script.
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "font-src 'self' data: https://fonts.gstatic.com; connect-src 'self'; worker-src blob:; "
    "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
)

DOCS_PATHS = ("/docs", "/redoc")
HSTS_VALUE = "max-age=31536000; includeSubDomains"

_STATIC_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


def security_headers_enabled() -> bool:
    """Return whether security headers are enabled (SECURITY_HEADERS_ENABLED, default true)."""
    return os.environ.get("SECURITY_HEADERS_ENABLED", "true").lower() not in ("false", "0", "no")


class SecurityHeadersMiddleware:
    """Pure ASGI middleware adding security headers to every HTTP response.

    Headers already set by the application are never overwritten. HSTS is sent when BASE_URL
    is https or the request itself arrived over https.
    """

    def __init__(self, app: ASGIApp, base_url: str = "") -> None:
        self.app = app
        self.force_hsts = base_url.lower().startswith("https://")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_docs = path in DOCS_PATHS
        add_hsts = self.force_hsts or scope.get("scheme") == "https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                defaults = {**_STATIC_HEADERS, "content-security-policy": DOCS_CSP if is_docs else SPA_CSP}
                if add_hsts:
                    defaults["strict-transport-security"] = HSTS_VALUE
                for name, value in defaults.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
