"""Pure arithmetic of parallel, resumable downloads: chunks, saved state, speed and throttling."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "MIB",
    "MIN_CHUNK_SIZE",
    "REFRESH_MARGIN",
    "Chunk",
    "PartState",
    "RateMeter",
    "Throttle",
    "content_range_total",
    "expires_soon",
    "plan_chunks",
    "range_header",
]

MIB = 1 << 20
# YouTube slows VISIONOS range requests of 8 MiB to about 150 KB/s after a burst, while 4 MiB
# and smaller ones run at full speed (measured 2026-10-09); 2 MiB leaves a margin.
DEFAULT_CHUNK_SIZE = 2 * MIB
MIN_CHUNK_SIZE = 256 * 1024
REFRESH_MARGIN = 300.0
_STATE_VERSION = 1


@dataclass(frozen=True, slots=True)
class Chunk:
    """Bytes ``start`` to ``end`` (exclusive) of one stream."""

    index: int
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start


def plan_chunks(size: int, chunk_size: int) -> tuple[Chunk, ...]:
    """Split ``size`` bytes into ``chunk_size`` pieces; streams under two pieces stay whole."""
    if size <= 0:
        return ()
    if size < 2 * chunk_size:
        return (Chunk(0, 0, size),)
    return tuple(
        Chunk(index, start, min(start + chunk_size, size))
        for index, start in enumerate(range(0, size, chunk_size))
    )


def range_header(start: int, end: int) -> str:
    """The ``Range`` header value for bytes ``start`` to ``end`` (exclusive)."""
    return f"bytes={start}-{end - 1}"


def content_range_total(value: str | None) -> int | None:
    """The total size in ``Content-Range: bytes 0-0/12345`` (or ``bytes */12345``)."""
    if not value:
        return None
    unit, _, rest = value.strip().partition(" ")
    total = rest.rpartition("/")[2]
    if unit.lower() != "bytes" or not (total.isascii() and total.isdigit()):
        return None
    return int(total)


def expires_soon(expires_at: int | None, now: float, margin: float = REFRESH_MARGIN) -> bool:
    """True when a URL expiring at ``expires_at`` (Unix seconds) has less than ``margin`` left."""
    return expires_at is not None and expires_at - now < margin


@dataclass(frozen=True, slots=True)
class PartState:
    """What a ``.part`` file holds; saved next to it as ``.part.json``."""

    video_id: str
    itag: int
    content_length: int
    last_modified: str
    chunk_size: int
    completed: frozenset[int] = frozenset()

    def to_json(self) -> str:
        """Compact JSON, finished chunk numbers sorted."""
        return json.dumps(
            {
                "version": _STATE_VERSION,
                "video_id": self.video_id,
                "itag": self.itag,
                "content_length": self.content_length,
                "last_modified": self.last_modified,
                "chunk_size": self.chunk_size,
                "completed": sorted(self.completed),
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, text: str) -> PartState | None:
        """The state saved in ``text``; ``None`` when it is damaged or from another version."""
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("version") != _STATE_VERSION:
            return None
        try:
            return cls(
                video_id=str(data["video_id"]),
                itag=int(data["itag"]),
                content_length=int(data["content_length"]),
                last_modified=str(data["last_modified"]),
                chunk_size=int(data["chunk_size"]),
                completed=frozenset(int(index) for index in data["completed"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def matches(self, other: PartState) -> bool:
        """Same video, stream, size, version and chunking, so finished chunks can be reused."""
        return self._identity == other._identity

    @property
    def _identity(self) -> tuple[str, int, int, str, int]:
        return (self.video_id, self.itag, self.content_length, self.last_modified, self.chunk_size)


class RateMeter:
    """Download speed over the last ``window`` seconds, and the time left at that speed."""

    def __init__(self, window: float = 5.0) -> None:
        self._window = window
        self._samples: deque[tuple[float, int]] = deque()

    def update(self, now: float, done: int, total: int | None) -> tuple[float | None, float | None]:
        """Record ``done`` bytes at ``now``; return (bytes per second, seconds left)."""
        self._samples.append((now, done))
        while len(self._samples) > 2 and now - self._samples[1][0] >= self._window:
            self._samples.popleft()
        start, first = self._samples[0]
        if now <= start:
            return None, None
        speed = (done - first) / (now - start)
        if total is None or speed <= 0:
            return speed, None
        return speed, max(0.0, (total - done) / speed)


class Throttle:
    """Lets an event through at most once per ``interval`` seconds; the first always passes."""

    def __init__(self, interval: float = 0.25) -> None:
        self._interval = interval
        self._last: float | None = None

    def ready(self, now: float, *, force: bool = False) -> bool:
        if force or self._last is None or now - self._last >= self._interval:
            self._last = now
            return True
        return False
