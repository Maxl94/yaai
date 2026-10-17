"""Unit tests for safe static file resolution."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yaai.server.spa import is_api_path, mount_spa, resolve_static_file


@pytest.fixture
def static_dir(tmp_path):
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("index")
    (root / "assets" / "app.js").write_text("js")
    # Shares the "static" prefix: str.startswith() would wrongly treat it as inside the root.
    evil = tmp_path / "static_evil"
    evil.mkdir()
    (evil / "secret.txt").write_text("secret")
    (tmp_path / "outside.txt").write_text("outside")
    return root


def test_resolves_existing_file(static_dir):
    assert resolve_static_file(static_dir, "assets/app.js") == (static_dir / "assets" / "app.js").resolve()


def test_missing_file_returns_none(static_dir):
    assert resolve_static_file(static_dir, "dashboard/models") is None


def test_directory_returns_none(static_dir):
    assert resolve_static_file(static_dir, "assets") is None


@pytest.mark.parametrize("requested", ["../outside.txt", "assets/../../outside.txt", "../static_evil/secret.txt"])
def test_parent_traversal_returns_none(static_dir, requested):
    assert resolve_static_file(static_dir, requested) is None


def test_sibling_directory_with_same_prefix_returns_none(static_dir):
    assert resolve_static_file(static_dir, "../static_evil/secret.txt") is None


def test_absolute_path_returns_none(static_dir, tmp_path):
    assert resolve_static_file(static_dir, str(tmp_path / "outside.txt")) is None


def test_symlink_escaping_root_returns_none(static_dir, tmp_path):
    (static_dir / "link.txt").symlink_to(tmp_path / "outside.txt")
    assert resolve_static_file(static_dir, "link.txt") is None


def test_null_byte_returns_none(static_dir):
    assert resolve_static_file(static_dir, "a\x00b") is None


@pytest.mark.parametrize(
    ("requested", "expected"),
    [("api", True), ("api/v1/does-not-exist", True), ("api/v2/x", True), ("apiary", False), ("models/123", False)],
)
def test_is_api_path(requested, expected):
    assert is_api_path(requested, "/api/v1") is expected


@pytest.fixture
def client(static_dir):
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    mount_spa(app, static_dir, "/api/v1")
    return TestClient(app)


def test_known_api_route_still_served(client):
    assert client.get("/api/v1/ping").json() == {"ok": True}


@pytest.mark.parametrize("path", ["/api/v1/does-not-exist", "/api/anything", "/api"])
def test_unknown_api_path_returns_json_404(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Not Found"}


def test_spa_deep_link_serves_index(client):
    response = client.get("/models/123")
    assert response.status_code == 200
    assert response.text == "index"


def test_static_asset_is_served(client):
    assert client.get("/assets/app.js").text == "js"
