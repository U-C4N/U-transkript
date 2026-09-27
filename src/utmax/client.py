"""The Client: configuration plus one connection pipeline that every call goes through."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self

from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.errors import InvalidOption
from utmax.models import TrackList, Transcript, VideoInfo
from utmax.services.transcripts import TranscriptService
from utmax.transport import Transport

__all__ = ["Client"]


class Client:
    """A configured, thread-safe connection to YouTube.

    Module-level functions such as :func:`utmax.fetch` share a default ``Client``. Create your
    own for a proxy, timeouts or a retry policy::

        with utmax.Client(proxy="http://user:pass@host:8080", timeout=20) as client:
            transcript = client.fetch("dQw4w9WgXcQ")

    Args:
        proxy: ``http://[user:password@]host:port`` used for all YouTube traffic.
        timeout: seconds before a request is abandoned.
        retries: extra attempts for timeouts, connection resets and HTTP 408/5xx.
        block_retries: extra attempts, each on a new connection, when YouTube blocks the IP
            (useful with rotating proxies).
        transport: a custom :class:`utmax.transport.Transport` replacing the whole HTTP stack;
            ``timeout`` and ``retries`` are then ignored and ``proxy`` must not be set.
    """

    def __init__(
        self,
        *,
        proxy: str | None = None,
        timeout: float = 30.0,
        retries: int = 2,
        block_retries: int = 0,
        transport: Transport | None = None,
    ) -> None:
        if timeout <= 0:
            raise InvalidOption("timeout must be a positive number of seconds.")
        if retries < 0 or block_retries < 0:
            raise InvalidOption("retries and block_retries cannot be negative.")
        if transport is not None and proxy is not None:
            raise InvalidOption(
                "Pass either proxy= or transport=, not both; configure the proxy in your transport."
            )
        if transport is None:
            transport = RetryingTransport(
                UrllibTransport(proxy=proxy, timeout=timeout), retries=retries
            )
        self._transcripts = TranscriptService(
            InnerTubeClient(transport, block_retries=block_retries)
        )

    def fetch(
        self,
        video: str,
        languages: Sequence[str] | str | None = None,
        *,
        include_manual: bool = True,
        include_generated: bool = True,
        preserve_formatting: bool = False,
        youtube_translation: str | None = None,
    ) -> Transcript:
        """Fetch the best subtitle track of ``video``; see :func:`utmax.fetch`."""
        return self._transcripts.fetch(
            video,
            languages,
            include_manual=include_manual,
            include_generated=include_generated,
            preserve_formatting=preserve_formatting,
            youtube_translation=youtube_translation,
        )

    def list_tracks(self, video: str) -> TrackList:
        """Every subtitle track of ``video``, in YouTube's order."""
        return self._transcripts.list_tracks(video)

    def video_info(self, video: str) -> VideoInfo:
        """Title, channel and duration of ``video``."""
        return self._transcripts.video_info(video)

    def close(self) -> None:
        """Release resources; utmax keeps no open connections today, so this does nothing yet."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
