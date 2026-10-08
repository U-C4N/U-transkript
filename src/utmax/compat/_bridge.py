"""How utmax.compat reaches YouTube: utmax's transports and InnerTube client, with utmax errors
turned into the exceptions of youtube-transcript-api."""

from __future__ import annotations

import re
from typing import Any

from utmax import errors
from utmax.adapters.http import RetryingTransport, UrllibTransport, redact
from utmax.adapters.innertube import InnerTubeClient
from utmax.compat._errors import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    FailedToCreateConsentCookie,
    InvalidVideoId,
    IpBlocked,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)
from utmax.compat.proxies import InvalidProxyConfig, ProxyConfig
from utmax.core.ids import parse_video_id
from utmax.core.player import PlayerData
from utmax.transport import HttpRequest, HttpResponse, Transport

__all__ = [
    "TIMEOUT",
    "Connection",
    "SessionTransport",
    "compat_error",
    "connection_for",
    "make_transport",
    "video_id_of",
]

TIMEOUT = 30.0
"""Seconds before a request is abandoned (also passed to an ``http_client``)."""

_SIMPLE_ERRORS: tuple[tuple[type[errors.UTMaxError], type[CouldNotRetrieveTranscript]], ...] = (
    (errors.VideoUnavailable, VideoUnavailable),
    (errors.AgeRestricted, AgeRestricted),
    (errors.PoTokenRequired, PoTokenRequired),
    (errors.FailedToCreateConsentCookie, FailedToCreateConsentCookie),
    (errors.YouTubeDataUnparsable, YouTubeDataUnparsable),
    (errors.TranscriptsDisabled, TranscriptsDisabled),
    (errors.InvalidVideoId, InvalidVideoId),
)
_DECODED_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})
_QUERY_RUN = re.compile(r"\?[^\s)'\"]+")
"""A ``?`` and what follows it up to whitespace, a closing parenthesis or a quote."""


class SessionTransport:
    """Sends utmax's requests through a ``requests.Session``-like ``http_client``.

    The client needs ``request(method, url, headers=..., data=..., timeout=...)`` returning an
    object with ``status_code``, ``headers`` and ``content`` (the decoded body); that is how
    SOCKS proxies, custom certificates or shared cookies reach utmax without utmax depending on
    requests.
    """

    def __init__(self, session: Any, *, timeout: float = TIMEOUT) -> None:
        self._session = session
        self._timeout = timeout

    def send(self, request: HttpRequest) -> HttpResponse:
        try:
            response = self._session.request(
                request.method,
                request.url,
                headers=dict(request.headers),
                data=request.body,
                timeout=self._timeout,
            )
        except Exception as error:  # the session's own exception types are unknown here
            reason = _without_query(str(error), request.url)
            raise errors.NetworkError(
                f"Could not complete {request.method} {redact(request.url)}: {reason}"
            ) from error
        headers = {
            str(name): str(value)
            for name, value in response.headers.items()
            if str(name).lower() not in _DECODED_HEADERS
        }
        return HttpResponse(
            status=int(response.status_code),
            url=request.url,
            headers=headers,
            body=bytes(response.content),
        )


def _without_query(text: str, url: str) -> str:
    """``text`` without the query string of ``url`` and without any other ``?...`` run.

    A session's own error text repeats the request (``Max retries exceeded with url:
    /api/timedtext?...&sig=...``), and the query of a caption URL holds the client's IP address,
    an expiry time and a signature, none of which belongs in a message (spec section 7).
    """
    query = url.partition("?")[2].partition("#")[0]
    if query:
        text = text.replace(f"?{query}", "").replace(query, "")
    return _QUERY_RUN.sub("", text)


def make_transport(http_client: Any, proxy_config: ProxyConfig | None) -> Transport:
    """The transport for an ``http_client`` (used as given) or for utmax's own HTTP stack.

    Raises:
        InvalidProxyConfig: utmax's own stack cannot use the proxy of ``proxy_config``.
    """
    if http_client is not None:
        return SessionTransport(http_client)
    proxy = proxy_config.to_requests_dict()["https"] if proxy_config is not None else None
    try:
        inner = UrllibTransport(proxy=proxy, timeout=TIMEOUT)
    except errors.InvalidOption as error:
        raise InvalidProxyConfig(
            f"{error} Without an http_client only http:// proxies work; for https:// or "
            "SOCKS proxies pass http_client=requests.Session() to YouTubeTranscriptApi."
        ) from error
    return RetryingTransport(inner)


class Connection:
    """utmax's InnerTube client behind one ``YouTubeTranscriptApi`` and its transcripts."""

    def __init__(self, transport: Transport, *, proxy_config: ProxyConfig | None = None) -> None:
        retries = proxy_config.retries_when_blocked if proxy_config is not None else 0
        self._innertube = InnerTubeClient(transport, block_retries=max(0, retries))
        self.proxy_config = proxy_config

    def player(self, video: str) -> tuple[str, PlayerData]:
        """The video ID in ``video`` and its player response, which lists subtitle tracks.

        Raises:
            CouldNotRetrieveTranscript: the subclass matching what went wrong.
        """
        video_id = video_id_of(video)
        try:
            player = self._innertube.player(video_id, purpose="captions")
        except errors.UTMaxError as error:
            raise compat_error(error, video_id, self.proxy_config) from error
        if not player.caption_tracks:
            raise TranscriptsDisabled(video_id)
        return video_id, player

    def caption_text(self, url: str, video_id: str) -> str:
        """The legacy XML of the caption track at ``url``.

        Raises:
            CouldNotRetrieveTranscript: the subclass matching what went wrong.
        """
        try:
            response = self._innertube.fetch_captions(url, video_id=video_id, fmt=None)
        except errors.UTMaxError as error:
            raise compat_error(error, video_id) from error
        return response.text


def connection_for(http_client: Any) -> Connection:
    """The connection of a ``Transcript``: the one utmax made, or one around ``http_client``."""
    if isinstance(http_client, Connection):
        return http_client
    return Connection(make_transport(http_client, None))


def video_id_of(video: str) -> str:
    """The ID in ``video``, a bare video ID or any YouTube video URL.

    Raises:
        InvalidVideoId: ``video`` is a URL without a video ID.
        VideoUnavailable: ``video`` cannot be a video ID (what YouTube would answer).
    """
    try:
        return parse_video_id(video)
    except errors.InvalidVideoId:
        if video.startswith(("http://", "https://")):
            raise InvalidVideoId(video) from None
        raise VideoUnavailable(video) from None


def compat_error(
    error: errors.UTMaxError, video_id: str, proxy_config: ProxyConfig | None = None
) -> CouldNotRetrieveTranscript:
    """The youtube-transcript-api exception for a utmax error.

    Blocks carry ``proxy_config`` (their message depends on it). Network failures and any other
    error become ``YouTubeRequestFailed`` with the utmax message as the reason.
    """
    if isinstance(error, errors.IpBlocked):
        return IpBlocked(video_id).with_proxy_config(proxy_config)
    if isinstance(error, errors.RequestBlocked):
        return RequestBlocked(video_id).with_proxy_config(proxy_config)
    if isinstance(error, errors.VideoUnplayable):
        return VideoUnplayable(video_id, error.reason or None, list(error.sub_reasons))
    for source, target in _SIMPLE_ERRORS:
        if isinstance(error, source):
            return target(video_id)
    return YouTubeRequestFailed(video_id, error)
