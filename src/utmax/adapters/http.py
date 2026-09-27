"""The only module that talks to the network: a urllib transport plus a retry wrapper."""

from __future__ import annotations

import gzip
import http.client
import logging
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from urllib.parse import urlsplit

from utmax.core.retry import backoff_delay, is_transient_status, parse_retry_after
from utmax.errors import InvalidOption, NetworkError
from utmax.transport import HttpRequest, HttpResponse, Transport

__all__ = ["RetryingTransport", "UrllibTransport", "redact"]

log = logging.getLogger("utmax.http")

_NETWORK_ERRORS = (OSError, http.client.HTTPException, EOFError)


class UrllibTransport:
    """Sends requests with the standard library; every request uses a fresh connection."""

    def __init__(self, *, proxy: str | None = None, timeout: float = 30.0) -> None:
        handlers: list[urllib.request.BaseHandler] = [
            urllib.request.HTTPSHandler(context=ssl.create_default_context())
        ]
        if proxy is not None:
            _check_proxy(proxy)
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self._opener = urllib.request.build_opener(*handlers)
        self._timeout = timeout

    def send(self, request: HttpRequest) -> HttpResponse:
        prepared = urllib.request.Request(
            request.url, data=request.body, headers=dict(request.headers), method=request.method
        )
        status: int
        headers: dict[str, str]
        body: bytes
        try:
            with self._opener.open(prepared, timeout=self._timeout) as response:
                status = response.status
                headers = dict(response.headers.items())
                body = response.read()
        except urllib.error.HTTPError as error:
            with error:
                status = error.code
                headers = dict(error.headers.items()) if error.headers else {}
                body = error.read()
        if _header(headers, "content-encoding").lower() == "gzip":
            body = gzip.decompress(body)
        log.debug("%s %s -> %d", request.method, redact(request.url), status)
        return HttpResponse(status=status, url=request.url, headers=headers, body=body)


class RetryingTransport:
    """Retries timeouts, connection resets and HTTP 408/5xx with exponential backoff."""

    def __init__(
        self,
        inner: Transport,
        *,
        retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._inner = inner
        self._retries = retries
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._clock = clock or _utc_now

    def send(self, request: HttpRequest) -> HttpResponse:
        attempt = 0
        while True:
            try:
                response = self._inner.send(request)
            except _NETWORK_ERRORS as error:
                if attempt >= self._retries or not _is_transient(error):
                    raise _network_error(error, request) from error
                delay = backoff_delay(attempt, self._rng)
                log.info(
                    "%s %s failed (%s); retrying in %.1fs",
                    request.method,
                    redact(request.url),
                    error,
                    delay,
                )
            else:
                if attempt >= self._retries or not is_transient_status(response.status):
                    return response
                retry_after = parse_retry_after(response.header("retry-after"), now=self._clock())
                delay = backoff_delay(attempt, self._rng) if retry_after is None else retry_after
                log.info(
                    "%s %s answered %d; retrying in %.1fs",
                    request.method,
                    redact(request.url),
                    response.status,
                    delay,
                )
            self._sleep(delay)
            attempt += 1


def redact(url: str) -> str:
    """``url`` without credentials or query string, safe for logs and error messages."""
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "<invalid url>"
    return f"{parts.scheme}://{parts.hostname or ''}{port}{parts.path}"


def _check_proxy(proxy: str) -> None:
    try:
        parts = urlsplit(proxy)
        host = parts.hostname
    except ValueError:
        host = None
    if not proxy.startswith("http://") or not host:
        raise InvalidOption(
            f"Unsupported proxy URL {redact(proxy)!r}: use http://[user:password@]host:port "
            "(HTTPS traffic is tunnelled through it).",
            suggestion="For SOCKS or https:// proxies, pass your own transport= to utmax.Client.",
        )


def _header(headers: Mapping[str, str], name: str) -> str:
    return next((value for key, value in headers.items() if key.lower() == name), "")


def _is_transient(error: BaseException) -> bool:
    reason: object = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return False
    if isinstance(reason, socket.gaierror):
        return reason.errno == socket.EAI_AGAIN
    return isinstance(
        reason,
        (
            TimeoutError,
            ConnectionError,
            ssl.SSLError,
            http.client.HTTPException,
            EOFError,
            gzip.BadGzipFile,
        ),
    )


def _network_error(error: BaseException, request: HttpRequest) -> NetworkError:
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    message = f"Could not complete {request.method} {redact(request.url)}: {reason}"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return NetworkError(
            message,
            suggestion=(
                "TLS certificate verification failed; a proxy or antivirus may be "
                "intercepting HTTPS traffic."
            ),
        )
    return NetworkError(message)


def _utc_now() -> datetime:
    return datetime.now(UTC)
