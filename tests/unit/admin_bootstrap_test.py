"""Unit tests for initial admin password handling."""

import logging
import os
import stat

import pytest

from yaai.server.admin_bootstrap import deliver_generated_password, resolve_admin_password


class TestResolveAdminPassword:
    def test_generates_password_when_not_configured(self, monkeypatch):
        monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
        password, generated = resolve_admin_password()
        assert generated is True
        assert len(password) >= 16

    def test_uses_configured_password(self, monkeypatch):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "a-long-enough-password")
        assert resolve_admin_password() == ("a-long-enough-password", False)

    def test_rejects_short_configured_password(self, monkeypatch):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "short")
        with pytest.raises(RuntimeError, match="at least 12"):
            resolve_admin_password()

    def test_accepts_minimum_length(self, monkeypatch):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "x" * 12)
        assert resolve_admin_password()[1] is False


class TestDeliverGeneratedPassword:
    def test_writes_file_with_owner_only_permissions(self, monkeypatch, tmp_path):
        target = tmp_path / "pw.txt"
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", str(target))

        deliver_generated_password("s3cret-value")

        assert "s3cret-value" in target.read_text()
        assert stat.S_IMODE(os.stat(target).st_mode) == 0o600

    def test_tightens_permissions_of_existing_file(self, monkeypatch, tmp_path):
        target = tmp_path / "pw.txt"
        target.write_text("old")
        target.chmod(0o644)
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", str(target))

        deliver_generated_password("s3cret-value")

        assert stat.S_IMODE(os.stat(target).st_mode) == 0o600

    def test_password_is_never_logged(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", str(tmp_path / "pw.txt"))

        with caplog.at_level(logging.DEBUG):
            deliver_generated_password("s3cret-value")

        assert "s3cret-value" not in caplog.text
        assert "pw.txt" in caplog.text

    def test_falls_back_to_stderr_once_when_file_not_writable(self, monkeypatch, tmp_path, capsys, caplog):
        monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD_FILE", str(tmp_path / "missing-dir" / "pw.txt"))

        with caplog.at_level(logging.DEBUG):
            deliver_generated_password("s3cret-value")

        err = capsys.readouterr().err
        assert err.count("s3cret-value") == 1
        assert "s3cret-value" not in caplog.text
