"""Unit tests for the rate limit key function."""

import pytest
from starlette.requests import Request

from yaai.server.rate_limit import get_client_key


def _request(forwarded_for: str | list[str] | None = None, client: str | None = "10.0.0.9") -> Request:
    lines = [forwarded_for] if isinstance(forwarded_for, str) else (forwarded_for or [])
    headers = [(b"x-forwarded-for", line.encode()) for line in lines]
    scope = {"type": "http", "headers": headers, "client": (client, 1234) if client else None}
    return Request(scope)


def test_defaults_to_socket_peer_and_ignores_forwarded_header(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", raising=False)
    assert get_client_key(_request("1.2.3.4")) == "10.0.0.9"


def test_single_hop_uses_rightmost_entry(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    assert get_client_key(_request("203.0.113.7")) == "203.0.113.7"


def test_spoofed_leftmost_entries_are_ignored(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    assert get_client_key(_request("6.6.6.6, 7.7.7.7, 203.0.113.7")) == "203.0.113.7"


def test_two_hops_use_second_from_right(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "2")
    assert get_client_key(_request("6.6.6.6, 203.0.113.7, 35.191.0.1")) == "203.0.113.7"


def test_falls_back_to_peer_when_header_missing(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    assert get_client_key(_request(None)) == "10.0.0.9"


def test_falls_back_to_peer_when_fewer_entries_than_hops(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "3")
    assert get_client_key(_request("203.0.113.7")) == "10.0.0.9"


@pytest.mark.parametrize("value", ["abc", "-1", "0", ""])
def test_invalid_or_non_positive_hops_use_peer(monkeypatch, value):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", value)
    assert get_client_key(_request("1.2.3.4")) == "10.0.0.9"


def test_multiple_header_lines_are_treated_as_one_list(monkeypatch):
    # A proxy that adds its own header line instead of appending leaves the client-supplied line first.
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    assert get_client_key(_request(["6.6.6.6", "203.0.113.7"])) == "203.0.113.7"


def test_multiple_header_lines_with_two_hops(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "2")
    assert get_client_key(_request(["6.6.6.6, 7.7.7.7", "203.0.113.7", "35.191.0.1"])) == "203.0.113.7"


def test_multiple_header_lines_with_spoofed_first_line_cannot_win(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    assert get_client_key(_request(["1.1.1.1, 2.2.2.2", "203.0.113.7"])) != "1.1.1.1"


def test_falls_back_to_peer_when_selected_entry_is_not_an_ip(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    assert get_client_key(_request("203.0.113.7, not-an-ip")) == "10.0.0.9"


def test_supports_ipv6_entries(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY_HOPS", "1")
    assert get_client_key(_request("2001:db8::1")) == "2001:db8::1"
