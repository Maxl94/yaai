"""Unit tests for safe static file resolution."""

import pytest

from yaai.server.spa import resolve_static_file


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
