"""A fake googlevideo server for download tests: byte ranges of in-memory streams, and faults.

Streams live at ``https://media.test/<name>``. The query string is ignored when looking up
the bytes, so a refreshed URL (``...?v=2``) serves the same stream, while URLs listed in
``expired`` answer 403.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit

from utmax.core.streams import Stream
from utmax.errors import NetworkError
from utmax.models import Format
from utmax.transport import HttpRequest, HttpResponse

BASE = "https://media.test/"


def pattern(size: int, seed: int = 0) -> bytes:
    """``size`` bytes that differ at every offset within 256 bytes (and between seeds)."""
    return bytes((seed + index * 7) % 256 for index in range(size))


def media_stream(
    itag: int,
    url: str,
    size: int | None,
    *,
    audio: bool = False,
    last_modified: str = "1",
    expires_at: int | None = None,
) -> Stream:
    """A stream for downloader tests (codec details do not matter there)."""
    fmt = Format(
        itag,
        "audio" if audio else "video",
        "mp4",
        "aac" if audio else "h264",
        "mp4a.40.2" if audio else "avc1.640028",
        content_length=size,
        last_modified=last_modified,
    )
    return Stream(fmt, url=url, expires_at=expires_at, user_agent="test-agent")


@dataclass(frozen=True)
class Fault:
    """Something that goes wrong with one request."""

    status: int | None = None  # answer with this status and an empty body
    cut_after: int | None = None  # end the body early, after this many bytes
    reset_after: int | None = None  # raise NetworkError after this many bytes
    error: BaseException | None = None  # raise this when the request is opened
    ignore_range: bool = False  # answer 200 with the whole stream


class FakeBody:
    """One response body; remembers whether it was closed."""

    def __init__(
        self,
        status: int,
        headers: dict[str, str],
        data: bytes,
        *,
        reset_after: int | None = None,
    ) -> None:
        self.status = status
        self.headers = {key.lower(): value for key, value in headers.items()}
        self.closed = False
        self._data = data
        self._position = 0
        self._reset_after = reset_after

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    def read(self, n: int) -> bytes:
        end = min(self._position + n, len(self._data))
        if self._reset_after is not None and end > self._reset_after:
            if self._position >= self._reset_after:
                raise NetworkError("Could not complete GET https://media.test: connection reset")
            end = self._reset_after
        data = self._data[self._position : end]
        self._position = end
        return data

    def close(self) -> None:
        self.closed = True


class FakeMedia:
    """Serves streams by name; thread-safe; records every request and every body."""

    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self.bodies: list[FakeBody] = []
        self.expired: set[str] = set()
        # name -> bytes served without a proof-of-origin token; requests past them answer 403
        self.start_only: dict[str, int] = {}
        self._streams: dict[str, bytes] = {}
        self._faults: dict[str, deque[Fault]] = {}
        self._lock = threading.Lock()

    def add(self, name: str, data: bytes) -> str:
        """Serve ``data`` as ``name`` and return its URL."""
        self._streams[name] = data
        return BASE + name

    def fail(self, name: str, *faults: Fault) -> None:
        """Apply ``faults`` to the next requests for ``name``, one fault per request."""
        self._faults.setdefault(name, deque()).extend(faults)

    def ranges(self, name: str) -> list[str]:
        """The ``Range`` headers of every request for ``name``, in order."""
        return [
            request.headers.get("Range", "")
            for request in self.requests
            if urlsplit(request.url).path == f"/{name}"
        ]

    def stream(self, request: HttpRequest) -> FakeBody:
        name = urlsplit(request.url).path.lstrip("/")
        with self._lock:
            self.requests.append(request)
            faults = self._faults.get(name)
            fault = faults.popleft() if faults else Fault()
        if fault.error is not None:
            raise fault.error
        body = self._answer(request, self._streams.get(name), fault, self.start_only.get(name))
        with self._lock:
            self.bodies.append(body)
        return body

    def send(self, request: HttpRequest) -> HttpResponse:
        """The whole answer at once, for code paths that cannot stream."""
        body = self.stream(request)
        data = body.read(1 << 40)
        body.close()
        return HttpResponse(status=body.status, url=request.url, headers=body.headers, body=data)

    def _answer(
        self, request: HttpRequest, data: bytes | None, fault: Fault, limit: int | None
    ) -> FakeBody:
        if data is None:
            return FakeBody(404, {}, b"")
        if request.url in self.expired:
            return FakeBody(403, {}, b"")
        if fault.status is not None:
            return FakeBody(fault.status, {}, b"")
        header = request.headers.get("Range")
        if header is None or fault.ignore_range:
            if limit is not None and len(data) > limit:
                return FakeBody(403, {}, b"")
            return FakeBody(200, {"Content-Length": str(len(data))}, data)
        first, _, last = header.removeprefix("bytes=").partition("-")
        start = int(first)
        end = min(int(last) + 1 if last else len(data), len(data))
        if limit is not None and end > limit:
            return FakeBody(403, {}, b"")
        if start >= len(data):
            return FakeBody(416, {"Content-Range": f"bytes */{len(data)}"}, b"")
        body = data[start:end]
        if fault.cut_after is not None:
            body = body[: fault.cut_after]
        headers = {"Content-Range": f"bytes {start}-{end - 1}/{len(data)}"}
        return FakeBody(206, headers, body, reset_after=fault.reset_after)
