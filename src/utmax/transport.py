"""The HTTP seam: every YouTube request goes through a ``Transport``, which tests replace."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

__all__ = ["HttpRequest", "HttpResponse", "HttpStream", "StreamingTransport", "Transport"]


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """One HTTP request."""

    method: Literal["GET", "POST"]
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """One HTTP response, whatever its status; header names are stored lower-cased."""

    status: int
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", {k.lower(): v for k, v in self.headers.items()})

    def header(self, name: str) -> str | None:
        """A header value, looked up case-insensitively."""
        return self.headers.get(name.lower())

    @property
    def content_type(self) -> str:
        return self.header("content-type") or ""

    @property
    def text(self) -> str:
        """The body decoded as UTF-8 (undecodable bytes are replaced)."""
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """The body parsed as JSON; raises ``ValueError`` when it is not JSON."""
        return json.loads(self.body.decode("utf-8"))


class Transport(Protocol):
    """Sends requests. Returns a response for any HTTP status; raises only on network failure."""

    def send(self, request: HttpRequest) -> HttpResponse: ...


@runtime_checkable
class HttpStream(Protocol):
    """A response whose body is read piece by piece (media downloads).

    ``read`` returns up to ``n`` bytes and ``b""`` at the end of the body; it raises
    :class:`utmax.errors.NetworkError` when the connection fails half-way.
    """

    @property
    def status(self) -> int: ...

    def header(self, name: str) -> str | None: ...

    def read(self, n: int) -> bytes: ...

    def close(self) -> None: ...


@runtime_checkable
class StreamingTransport(Transport, Protocol):
    """A :class:`Transport` that can also stream bodies; utmax buffers them for other ones."""

    def stream(self, request: HttpRequest) -> HttpStream: ...
