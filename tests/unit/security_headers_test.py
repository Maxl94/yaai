"""Unit tests for the security headers middleware."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from yaai.server.security_headers import (
    DOCS_CSP,
    HSTS_VALUE,
    SPA_CSP,
    SecurityHeadersMiddleware,
    security_headers_enabled,
)


async def _ok(request):
    return PlainTextResponse("ok")


async def _custom_csp(request):
    return PlainTextResponse("ok", headers={"Content-Security-Policy": "default-src 'none'"})


def _make_app(base_url: str = "http://localhost:8000", docs_enabled: bool = True) -> Starlette:
    app = Starlette(routes=[Route("/", _ok), Route("/docs", _ok), Route("/redoc", _ok), Route("/custom", _custom_csp)])
    app.add_middleware(SecurityHeadersMiddleware, base_url=base_url, docs_enabled=docs_enabled)
    return app


async def _get(app: Starlette, path: str, base: str = "http://test"):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=base) as client:
        return await client.get(path)


async def test_adds_baseline_headers():
    resp = await _get(_make_app(), "/")

    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in resp.headers["permissions-policy"]
    assert resp.headers["content-security-policy"] == SPA_CSP


async def test_spa_csp_forbids_inline_scripts_and_framing():
    assert "script-src 'self';" in SPA_CSP
    assert "frame-ancestors 'none'" in SPA_CSP
    assert "object-src 'none'" in SPA_CSP


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
async def test_docs_get_strict_csp_when_docs_disabled(path):
    # With docs disabled these paths serve the SPA, which must never run under the relaxed CSP.
    resp = await _get(_make_app(docs_enabled=False), path)

    assert resp.headers["content-security-policy"] == SPA_CSP


async def test_docs_disabled_is_the_default():
    app = Starlette(routes=[Route("/docs", _ok)])
    app.add_middleware(SecurityHeadersMiddleware)

    assert (await _get(app, "/docs")).headers["content-security-policy"] == SPA_CSP


async def test_docs_get_relaxed_csp():
    resp = await _get(_make_app(), "/docs")

    assert resp.headers["content-security-policy"] == DOCS_CSP
    assert "https://cdn.jsdelivr.net" in DOCS_CSP
    assert "https://fastapi.tiangolo.com" in DOCS_CSP


async def test_headers_added_to_error_responses():
    resp = await _get(_make_app(), "/missing")

    assert resp.status_code == 404
    assert resp.headers["x-content-type-options"] == "nosniff"


async def test_does_not_override_existing_header():
    resp = await _get(_make_app(), "/custom")

    assert resp.headers["content-security-policy"] == "default-src 'none'"


async def test_no_hsts_over_plain_http():
    resp = await _get(_make_app("http://localhost:8000"), "/")

    assert "strict-transport-security" not in resp.headers


async def test_hsts_when_base_url_is_https():
    resp = await _get(_make_app("https://yaai.example.com"), "/")

    assert resp.headers["strict-transport-security"] == HSTS_VALUE


async def test_hsts_when_request_is_https():
    resp = await _get(_make_app("http://localhost:8000"), "/", base="https://test")

    assert resp.headers["strict-transport-security"] == HSTS_VALUE


@pytest.mark.parametrize(("value", "expected"), [(None, True), ("true", True), ("false", False), ("0", False)])
def test_security_headers_enabled_flag(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SECURITY_HEADERS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("SECURITY_HEADERS_ENABLED", value)
    assert security_headers_enabled() is expected
