"""Tests for the pure retry policy."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from utmax.core.retry import MAX_RETRY_AFTER, backoff_delay, is_transient_status, parse_retry_after

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "transient"),
    [
        (408, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (404, False),
        (429, False),
        (200, False),
    ],
)
def test_transient_statuses(status: int, transient: bool) -> None:
    assert is_transient_status(status) is transient


def test_backoff_grows_and_is_capped() -> None:
    rng = random.Random(1)
    delays = [backoff_delay(attempt, rng) for attempt in range(6)]
    for attempt, delay in enumerate(delays):
        base = min(8.0, 0.5 * 2**attempt)
        assert base <= delay <= base + 0.25
    assert backoff_delay(20, rng) <= 8.25


def test_retry_after_in_seconds() -> None:
    assert parse_retry_after("3", now=NOW) == 3.0
    assert parse_retry_after(" 120 ", now=NOW) == MAX_RETRY_AFTER


def test_retry_after_as_an_http_date() -> None:
    assert (
        parse_retry_after(format_datetime(NOW + timedelta(seconds=5), usegmt=True), now=NOW) == 5.0
    )
    assert (
        parse_retry_after(format_datetime(NOW - timedelta(seconds=5), usegmt=True), now=NOW) == 0.0
    )
    assert parse_retry_after("Sun, 27 Sep 2026 12:00:07 -0000", now=NOW) == 7.0


@pytest.mark.parametrize("value", [None, "", "   ", "soon", "-5"])
def test_unusable_retry_after_values(value: str | None) -> None:
    assert parse_retry_after(value, now=NOW) is None
