"""``YouTubeTranscriptApi``, compatible with youtube-transcript-api 1.2.4."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from utmax.compat._transcripts import FetchedTranscript, TranscriptList, TranscriptListFetcher
from utmax.compat.proxies import ProxyConfig

__all__ = [
    "FetchedTranscript",
    "ProxyConfig",
    "TranscriptList",
    "TranscriptListFetcher",
    "YouTubeTranscriptApi",
]


class YouTubeTranscriptApi:
    """Fetches transcripts with utmax; a drop-in replacement for youtube-transcript-api's class.

    Unlike youtube-transcript-api, an instance is thread-safe (unless ``http_client`` is not),
    and every method also accepts YouTube video URLs.

    Args:
        proxy_config: proxies for all requests, such as ``GenericProxyConfig`` or
            ``WebshareProxyConfig``. Without ``http_client`` only ``http://`` proxies work.
        http_client: a ``requests.Session``-like object that sends every request instead of
            utmax's own HTTP code: use it for SOCKS or HTTPS proxies, custom certificates or
            shared cookies.
    """

    def __init__(
        self,
        proxy_config: ProxyConfig | None = None,
        http_client: Any = None,
    ) -> None:
        if http_client is not None:
            http_client.headers.update({"Accept-Language": "en-US"})
            if proxy_config is not None:
                http_client.proxies = proxy_config.to_requests_dict()
                if proxy_config.prevent_keeping_connections_alive:
                    http_client.headers.update({"Connection": "close"})
        self._fetcher = TranscriptListFetcher(http_client, proxy_config=proxy_config)

    def fetch(
        self,
        video_id: str,
        languages: Iterable[str] = ("en",),
        preserve_formatting: bool = False,
    ) -> FetchedTranscript:
        """
        Retrieves the transcript for a single video. This is just a shortcut for
        calling:
        `YouTubeTranscriptApi().list(video_id).find_transcript(languages).fetch(preserve_formatting=preserve_formatting)`

        :param video_id: the ID or URL of the video you want to retrieve the transcript for.
        :param languages: A list of language codes in a descending priority. For
            example, if this is set to ["de", "en"] it will first try to fetch the
            german transcript (de) and then fetch the english transcript (en) if
            it fails to do so. This defaults to ["en"].
        :param preserve_formatting: whether to keep select HTML text formatting
        """
        return (
            self.list(video_id)
            .find_transcript(languages)
            .fetch(preserve_formatting=preserve_formatting)
        )

    def list(
        self,
        video_id: str,
    ) -> TranscriptList:
        """
        Retrieves the list of transcripts which are available for a given video. It
        returns a `TranscriptList` object which is iterable and provides methods to
        filter the list of transcripts for specific languages. While iterating over
        the `TranscriptList` the individual transcripts are represented by
        `Transcript` objects, which provide metadata and can either be fetched by
        calling `transcript.fetch()` or translated by calling `transcript.translate(
        'en')`.

        :param video_id: the ID or URL of the video you want to retrieve the transcript for.
        """
        return self._fetcher.fetch(video_id)
