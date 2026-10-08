"""``YouTubeTranscriptApi``, compatible with youtube-transcript-api 1.2.4 and the class methods
of 0.6."""

from __future__ import annotations

import builtins
import os
import warnings
from collections.abc import Iterable, Mapping
from typing import Any

from utmax.compat._transcripts import FetchedTranscript, TranscriptList, TranscriptListFetcher
from utmax.compat.proxies import GenericProxyConfig, ProxyConfig

__all__ = [
    "FetchedTranscript",
    "ProxyConfig",
    "TranscriptList",
    "TranscriptListFetcher",
    "YouTubeTranscriptApi",
]

_LegacyProxies = ProxyConfig | Mapping[str, str] | None
_RawTranscript = builtins.list[dict[str, Any]]


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

    @classmethod
    def list_transcripts(
        cls,
        video_id: str,
        proxies: _LegacyProxies = None,
        cookies: str | os.PathLike[str] | None = None,
    ) -> TranscriptList:
        """
        DEPRECATED: use the `list` method instead!

        The class method of youtube-transcript-api 0.6. ``proxies`` is a ``ProxyConfig`` or a
        requests-style ``{"http": url, "https": url}`` mapping; ``cookies`` is ignored with a
        warning, because cookie authentication is not supported.
        """
        warnings.warn(
            "`list_transcripts` is deprecated and will be removed in a future version. "
            "Use the `list` method instead!",
            DeprecationWarning,
            stacklevel=2,
        )
        if cookies:
            warnings.warn(
                "Cookie authentication is not supported; the cookies argument is ignored.",
                UserWarning,
                stacklevel=2,
            )
        return cls(proxy_config=_legacy_proxy_config(proxies)).list(video_id)

    @classmethod
    def get_transcripts(  # noqa: PLR0917
        cls,
        video_ids: builtins.list[str],
        languages: Iterable[str] = ("en",),
        continue_after_error: bool = False,
        proxies: _LegacyProxies = None,
        cookies: str | os.PathLike[str] | None = None,
        preserve_formatting: bool = False,
    ) -> tuple[dict[str, _RawTranscript], builtins.list[str]]:
        """
        DEPRECATED: use the `fetch` method instead!

        Retrieves the transcripts for a list of videos.

        :return: a tuple containing a dictionary mapping video ids onto their corresponding
            transcripts (lists of ``{"text", "start", "duration"}`` dictionaries), and a list of
            video ids, which could not be retrieved
        """
        warnings.warn(
            "`get_transcripts` is deprecated and will be removed in a future version. "
            "Use the `fetch` method instead!",
            DeprecationWarning,
            stacklevel=2,
        )
        if not isinstance(video_ids, builtins.list):
            raise AssertionError("`video_ids` must be a list of strings")

        data: dict[str, _RawTranscript] = {}
        unretrievable_videos: builtins.list[str] = []

        for video_id in video_ids:
            try:
                data[video_id] = cls.get_transcript(
                    video_id, languages, proxies, cookies, preserve_formatting
                )
            except Exception:
                if not continue_after_error:
                    raise

                unretrievable_videos.append(video_id)

        return data, unretrievable_videos

    @classmethod
    def get_transcript(
        cls,
        video_id: str,
        languages: Iterable[str] = ("en",),
        proxies: _LegacyProxies = None,
        cookies: str | os.PathLike[str] | None = None,
        preserve_formatting: bool = False,
    ) -> _RawTranscript:
        """
        DEPRECATED: use the `fetch` method instead!

        Retrieves the transcript for a single video as a list of ``{"text", "start",
        "duration"}`` dictionaries.
        """
        warnings.warn(
            "`get_transcript` is deprecated and will be removed in a future version. "
            "Use the `fetch` method instead!",
            DeprecationWarning,
            stacklevel=2,
        )
        if not isinstance(video_id, str):
            raise AssertionError("`video_id` must be a string")
        return (
            cls.list_transcripts(video_id, proxies, cookies)
            .find_transcript(languages)
            .fetch(preserve_formatting=preserve_formatting)
            .to_raw_data()
        )


def _legacy_proxy_config(proxies: _LegacyProxies) -> ProxyConfig | None:
    if not proxies:
        return None
    if isinstance(proxies, ProxyConfig):
        return proxies
    return GenericProxyConfig(http_url=proxies.get("http"), https_url=proxies.get("https"))
