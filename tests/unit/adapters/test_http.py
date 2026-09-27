"""Tests for the urllib transport and the retry wrapper."""

from __future__ import annotations

import random
import socket
import ssl
import urllib.error
import urllib.request
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from tests.helpers.fake_transport import FakeTransport
from tests.helpers.http_server import local_server
from utmax.adapters.http import RetryingTransport, UrllibTransport, redact
from utmax.errors import InvalidOption, NetworkError
from utmax.transport import HttpRequest, HttpResponse

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
REQUEST = HttpRequest("GET", "https://www.youtube.com/api?secret=1")


@pytest.fixture(autouse=True)
def no_environment_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "getproxies", dict)


@pytest.fixture
def server() -> Iterator[str]:
    with local_server() as url:
        yield url


def test_get_returns_status_headers_and_body(server: str) -> None:
    response = UrllibTransport().send(HttpRequest("GET", f"{server}/json"))
    assert response.status == 200
    assert response.header("Content-Type") == "application/json"
    assert response.json() == {"ok": True}


def test_gzip_bodies_are_decompressed(server: str) -> None:
    response = UrllibTransport().send(
        HttpRequest("GET", f"{server}/gzip", {"Accept-Encoding": "gzip"})
    )
    assert response.text == "zipped ♪"


def test_http_errors_are_returned_not_raised(server: str) -> None:
    response = UrllibTransport().send(HttpRequest("GET", f"{server}/missing"))
    assert (response.status, response.body) == (404, b"nope")


def test_post_sends_body_and_headers(server: str) -> None:
    headers = {"Content-Type": "application/json", "User-Agent": "utmax-test"}
    response = UrllibTransport().send(HttpRequest("POST", f"{server}/echo", headers, b'{"a": 1}'))
    assert response.json() == {
        "path": "/echo",
        "body": '{"a": 1}',
        "content_type": "application/json",
        "user_agent": "utmax-test",
    }


def test_timeouts_raise_so_the_retry_layer_can_decide(server: str) -> None:
    with pytest.raises((TimeoutError, urllib.error.URLError)):
        UrllibTransport(timeout=0.2).send(HttpRequest("GET", f"{server}/slow"))


def test_an_http_proxy_receives_absolute_urls(server: str) -> None:
    response = UrllibTransport(proxy=server).send(
        HttpRequest("GET", "http://example.invalid/hello")
    )
    assert response.json() == {"path": "http://example.invalid/hello"}


@pytest.mark.parametrize(
    "proxy",
    ["https://proxy.example:443", "socks5://127.0.0.1:1080", "proxy.example:8080", "http://"],
)
def test_unsupported_proxy_urls_are_rejected(proxy: str) -> None:
    with pytest.raises(InvalidOption):
        UrllibTransport(proxy=proxy)


def test_redact_drops_credentials_and_queries() -> None:
    assert redact("http://user:pw@proxy.example:8080/p?token=1") == "http://proxy.example:8080/p"
    assert redact("http://[::1") == "<invalid url>"


def ok(status: int = 200, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(status=status, url=REQUEST.url, headers=headers or {})


def retrying(
    *replies: HttpResponse | BaseException, retries: int = 2
) -> tuple[RetryingTransport, FakeTransport, list[float]]:
    inner = FakeTransport()
    inner.add("GET", "", *replies)
    sleeps: list[float] = []
    transport = RetryingTransport(
        inner, retries=retries, sleep=sleeps.append, rng=random.Random(0), clock=lambda: NOW
    )
    return transport, inner, sleeps


def test_transient_statuses_are_retried_with_backoff() -> None:
    transport, inner, sleeps = retrying(ok(503), ok(502), ok(200))
    assert transport.send(REQUEST).status == 200
    assert len(inner.requests) == 3
    assert 0.5 <= sleeps[0] <= 0.75
    assert 1.0 <= sleeps[1] <= 1.25


def test_retry_after_is_honoured() -> None:
    transport, _, sleeps = retrying(ok(503, {"Retry-After": "3"}), ok(200))
    assert transport.send(REQUEST).status == 200
    assert sleeps == [3.0]


def test_exhausted_retries_return_the_last_response() -> None:
    transport, inner, sleeps = retrying(ok(503), ok(503), ok(503))
    assert transport.send(REQUEST).status == 503
    assert (len(inner.requests), len(sleeps)) == (3, 2)


@pytest.mark.parametrize("status", [400, 403, 404, 429])
def test_client_errors_are_not_retried(status: int) -> None:
    transport, inner, sleeps = retrying(ok(status))
    assert transport.send(REQUEST).status == status
    assert (len(inner.requests), sleeps) == (1, [])


def test_connection_resets_are_retried() -> None:
    transport, _, _ = retrying(ConnectionResetError("reset"), ok())
    assert transport.send(REQUEST).status == 200


def test_corrupt_compressed_bodies_are_retried_then_reported() -> None:
    transport, _, _ = retrying(zlib.error("bad data"), ok())
    assert transport.send(REQUEST).status == 200
    transport, _, _ = retrying(zlib.error("bad"), zlib.error("bad"), zlib.error("bad"))
    with pytest.raises(NetworkError):
        transport.send(REQUEST)


def test_exhausted_network_errors_become_network_error() -> None:
    transport, inner, _ = retrying(TimeoutError("slow"), TimeoutError("slow"), TimeoutError("slow"))
    with pytest.raises(NetworkError) as caught:
        transport.send(REQUEST)
    assert isinstance(caught.value.__cause__, TimeoutError)
    assert "secret" not in str(caught.value)
    assert len(inner.requests) == 3


def test_certificate_errors_fail_fast_with_a_hint() -> None:
    transport, inner, _ = retrying(urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")))
    with pytest.raises(NetworkError) as caught:
        transport.send(REQUEST)
    assert "certificate" in caught.value.suggestion
    assert len(inner.requests) == 1


def test_temporary_dns_failures_are_retried_but_unknown_hosts_are_not() -> None:
    try_again = urllib.error.URLError(socket.gaierror(socket.EAI_AGAIN, "try again"))
    transport, _, _ = retrying(try_again, ok())
    assert transport.send(REQUEST).status == 200
    unknown = urllib.error.URLError(socket.gaierror(socket.EAI_NONAME, "unknown host"))
    transport, inner, _ = retrying(unknown)
    with pytest.raises(NetworkError):
        transport.send(REQUEST)
    assert len(inner.requests) == 1


def test_programming_errors_propagate_unchanged() -> None:
    transport, _, _ = retrying(ValueError("bad url"))
    with pytest.raises(ValueError, match="bad url"):
        transport.send(REQUEST)


def test_zero_retries_means_one_attempt() -> None:
    transport, inner, sleeps = retrying(ok(503), retries=0)
    assert transport.send(REQUEST).status == 503
    assert (len(inner.requests), sleeps) == (1, [])
