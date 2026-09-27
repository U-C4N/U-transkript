"""Pure retry policy: which HTTP statuses are transient and how long to wait."""

from __future__ import annotations

import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

__all__ = [
    "MAX_RETRY_AFTER",
    "TRANSIENT_STATUSES",
    "backoff_delay",
    "is_transient_status",
    "parse_retry_after",
]

TRANSIENT_STATUSES = frozenset({408, 500, 502, 503, 504})
MAX_RETRY_AFTER = 30.0


def is_transient_status(status: int) -> bool:
    """True for statuses worth retrying: 408 and 500/502/503/504 (429 is handled separately)."""
    return status in TRANSIENT_STATUSES


def backoff_delay(attempt: int, rng: random.Random) -> float:
    """Exponential backoff: 0.5 s, 1 s, 2 s … capped at 8 s, plus up to 0.25 s of jitter."""
    base = min(8.0, 0.5 * 2**attempt)
    return float(base) + rng.uniform(0.0, 0.25)


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Seconds to wait from a ``Retry-After`` header (seconds or HTTP date), capped at 30 s."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    if text.isascii() and text.isdigit():
        return min(float(text), MAX_RETRY_AFTER)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, min((when - now).total_seconds(), MAX_RETRY_AFTER))
