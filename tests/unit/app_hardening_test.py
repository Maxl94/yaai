"""Import-time behavior of the app in production/dev, verified in a fresh interpreter."""

import os
import subprocess
import sys

_PROBE = """
from starlette.testclient import TestClient
from yaai.server.main import app

client = TestClient(app)
docs = client.get("/docs")
spec = client.get("/openapi.json")
health = client.get("/health")
print(docs.status_code, spec.status_code, health.status_code)
print("swagger" in docs.text.lower(), '"openapi"' in spec.text)
print(health.headers.get("x-content-type-options"), "|", health.headers.get("content-security-policy"))
print(docs.headers.get("content-security-policy"))
"""


def _run(**env: str) -> subprocess.CompletedProcess:
    base = {k: v for k, v in os.environ.items() if k not in ("ENVIRONMENT", "SESSION_SECRET", "API_DOCS_ENABLED")}
    base["DATABASE_URL"] = "sqlite+aiosqlite://"
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE], env={**base, **env}, capture_output=True, text=True, timeout=120, check=False
    )


def test_prod_hides_api_docs_and_sets_security_headers():
    result = _run(ENVIRONMENT="production", SESSION_SECRET="a-strong-session-secret")  # noqa: S106

    assert result.returncode == 0, result.stderr
    status_line, docs_line, health_line, _ = result.stdout.strip().splitlines()
    # A built frontend may answer unknown paths with index.html (200); the docs must never be served.
    assert status_line.split()[:2] in (["404", "404"], ["200", "200"])
    assert docs_line == "False False"
    assert health_line.startswith("nosniff | default-src 'self'")


def test_dev_serves_api_docs_with_relaxed_csp():
    result = _run(ENVIRONMENT="development")

    assert result.returncode == 0, result.stderr
    status_line, docs_line, _, docs_csp = result.stdout.strip().splitlines()
    assert status_line.split() == ["200", "200", "200"]
    assert docs_line == "True True"
    assert "cdn.jsdelivr.net" in docs_csp


def test_prod_without_session_secret_fails_at_import():
    result = _run(ENVIRONMENT="production")

    assert result.returncode != 0
    assert "SESSION_SECRET must be set in production" in result.stderr
