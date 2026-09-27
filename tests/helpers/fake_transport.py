"""A scripted, thread-safe Transport for tests: no network, full control over replies."""

from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

from utmax.transport import HttpRequest, HttpResponse

Reply = HttpResponse | BaseException


def json_response(payload: Any, *, status: int = 200) -> HttpResponse:
    return HttpResponse(
        status=status,
        url="https://www.youtube.com/",
        headers={"Content-Type": "application/json; charset=UTF-8"},
        body=json.dumps(payload).encode("utf-8"),
    )


def text_response(
    text: str, *, status: int = 200, content_type: str = "text/html; charset=utf-8"
) -> HttpResponse:
    return HttpResponse(
        status=status,
        url="https://www.youtube.com/",
        headers={"Content-Type": content_type},
        body=text.encode("utf-8"),
    )


@dataclass
class _Route:
    method: str
    fragment: str
    replies: deque[Reply]
    repeat: bool


class FakeTransport:
    """Answers requests from scripted routes.

    Routes are checked in the order they were added; the first route whose method matches, whose
    ``url_fragment`` occurs in the URL and which still has replies wins. Replies are consumed in
    order unless ``repeat=True`` (then the first reply is served forever). Exceptions are raised.
    """

    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        self._routes: list[_Route] = []
        self._lock = threading.Lock()

    def add(self, method: str, url_fragment: str, *replies: Reply, repeat: bool = False) -> None:
        self._routes.append(_Route(method, url_fragment, deque(replies), repeat))

    def send(self, request: HttpRequest) -> HttpResponse:
        with self._lock:
            self.requests.append(request)
            for route in self._routes:
                if (
                    route.method == request.method
                    and route.fragment in request.url
                    and route.replies
                ):
                    reply = route.replies[0] if route.repeat else route.replies.popleft()
                    break
            else:
                raise AssertionError(f"unexpected request: {request.method} {request.url}")
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def urls(self, method: str | None = None) -> list[str]:
        return [r.url for r in self.requests if method is None or r.method == method]
