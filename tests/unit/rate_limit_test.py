"""Unit tests for the rate limit key function."""

import pytest
from starlette.requests import Request

from yaai.server.rate_limit import get_client_key


def _request(forwarded_for: str | None = None, client: str | None = "10.0.0.9") -> Request:
    headers = [(b"x-forwarded-for", forwarded_for.encode())] if forwarded_for is not None else []
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
