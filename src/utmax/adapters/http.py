"""The only module that talks to the network: a urllib transport plus a retry wrapper."""

from __future__ import annotations

import gzip
import http.client
import io
import logging
import random
import socket
import ssl
import time
import urllib.error
import urllib.request
import zlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import IO
from urllib.parse import urlsplit

from utmax.core.retry import backoff_delay, is_transient_status, parse_retry_after
from utmax.errors import InvalidOption, NetworkError
from utmax.transport import HttpRequest, HttpResponse, HttpStream, StreamingTransport, Transport

__all__ = ["BufferedStream", "RetryingTransport", "UrllibTransport", "open_stream", "redact"]

log = logging.getLogger("utmax.http")

_NETWORK_ERRORS = (OSError, http.client.HTTPException, EOFError, zlib.error)

# Binding outgoing sockets here makes every IPv6 address fail, so only IPv4 is tried.
_IPV4_ONLY = ("0.0.0.0", 0)


class UrllibTransport:
    """Sends requests with the standard library; every request uses a fresh connection.

    ``force_ipv4=True`` connects over IPv4 only. Stream URLs are bound to the address that
    requested them, so machines whose IPv4 and IPv6 addresses differ may need it.
    """

    def __init__(
        self, *, proxy: str | None = None, timeout: float = 30.0, force_ipv4: bool = False
    ) -> None:
        context = ssl.create_default_context()
        handlers: list[urllib.request.BaseHandler] = (
            [_IPv4HTTPHandler(), _IPv4HTTPSHandler(context)]
            if force_ipv4
            else [urllib.request.HTTPSHandler(context=context)]
        )
        if proxy is not None:
            _check_proxy(proxy)
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self._opener = urllib.request.build_opener(*handlers)
        self._timeout = timeout

    def send(self, request: HttpRequest) -> HttpResponse:
        status: int
        headers: dict[str, str]
        body: bytes
        try:
            with self._opener.open(_prepare(request), timeout=self._timeout) as response:
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

    def stream(self, request: HttpRequest) -> HttpStream:
        """Open ``request`` and hand back its body unread and never decompressed.

        Raises:
            NetworkError: the connection could not be made.
        """
        try:
            response = self._opener.open(_prepare(request), timeout=self._timeout)
        except urllib.error.HTTPError as error:
            log.debug("%s %s -> %d (stream)", request.method, redact(request.url), error.code)
            headers = dict(error.headers.items()) if error.headers else {}
            return _UrllibStream(error, error.code, headers, request)
        except _NETWORK_ERRORS as error:
            raise _network_error(error, request) from error
        log.debug("%s %s -> %d (stream)", request.method, redact(request.url), response.status)
        return _UrllibStream(response, response.status, dict(response.headers.items()), request)


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

    def stream(self, request: HttpRequest) -> HttpStream:
        """Stream through the inner transport; the downloader retries byte ranges itself."""
        return open_stream(self._inner, request)


def redact(url: str) -> str:
    """``url`` without credentials or query string, safe for logs and error messages."""
    try:
        parts = urlsplit(url)
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "<invalid url>"
    return f"{parts.scheme}://{parts.hostname or ''}{port}{parts.path}"


def open_stream(transport: Transport, request: HttpRequest) -> HttpStream:
    """Stream ``request`` when ``transport`` can; otherwise send it and serve the body from memory."""
    if isinstance(transport, StreamingTransport):
        return transport.stream(request)
    return BufferedStream(transport.send(request))


class BufferedStream:
    """An :class:`~utmax.transport.HttpStream` over a response that is already in memory."""

    def __init__(self, response: HttpResponse) -> None:
        self.status = response.status
        self._response = response
        self._body = io.BytesIO(response.body)

    def header(self, name: str) -> str | None:
        return self._response.header(name)

    def read(self, n: int) -> bytes:
        return self._body.read(n)

    def close(self) -> None:
        self._body.close()


class _UrllibStream:
    """A urllib response (or HTTP error response) whose body is read in pieces."""

    def __init__(
        self, body: IO[bytes], status: int, headers: Mapping[str, str], request: HttpRequest
    ) -> None:
        self.status = status
        self._body = body
        self._headers = {key.lower(): value for key, value in headers.items()}
        self._request = request

    def header(self, name: str) -> str | None:
        return self._headers.get(name.lower())

    def read(self, n: int) -> bytes:
        try:
            return self._body.read(n)
        except _NETWORK_ERRORS as error:
            raise _network_error(error, self._request) from error

    def close(self) -> None:
        self._body.close()


class _IPv4HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(http.client.HTTPConnection, req, source_address=_IPV4_ONLY)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, context: ssl.SSLContext) -> None:
        super().__init__(context=context)
        self._tls_context = context

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(
            http.client.HTTPSConnection,
            req,
            context=self._tls_context,
            source_address=_IPV4_ONLY,
        )


def _prepare(request: HttpRequest) -> urllib.request.Request:
    return urllib.request.Request(
        request.url, data=request.body, headers=dict(request.headers), method=request.method
    )


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
            zlib.error,
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
