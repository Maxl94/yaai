from datetime import timedelta

import pytest

from yaai.server.services.drift_service import parse_window_size


def test_short_format_days():
    assert parse_window_size("7d") == timedelta(days=7)


def test_short_format_hours():
    assert parse_window_size("24h") == timedelta(hours=24)


def test_short_format_weeks():
    assert parse_window_size("2w") == timedelta(weeks=2)


def test_long_format_singular():
    assert parse_window_size("1 day") == timedelta(days=1)
    assert parse_window_size("1 hour") == timedelta(hours=1)
    assert parse_window_size("1 week") == timedelta(weeks=1)


def test_long_format_plural():
    assert parse_window_size("7 days") == timedelta(days=7)
    assert parse_window_size("48 hours") == timedelta(hours=48)
    assert parse_window_size("4 weeks") == timedelta(weeks=4)


def test_whitespace_handling():
    assert parse_window_size("  7 days  ") == timedelta(days=7)
    assert parse_window_size("7d") == timedelta(days=7)


def test_case_insensitive():
    assert parse_window_size("7 DAYS") == timedelta(days=7)
    assert parse_window_size("7D") == timedelta(days=7)


def test_invalid_format():
    with pytest.raises(ValueError, match="Invalid window_size"):
        parse_window_size("invalid")


def test_invalid_no_number():
    with pytest.raises(ValueError, match="Invalid window_size"):
        parse_window_size("days")
