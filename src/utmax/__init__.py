"""u-transcript max: YouTube transcripts, AI translation and downloads with zero dependencies.

Quick start::

    import utmax

    transcript = utmax.fetch("https://youtu.be/dQw4w9WgXcQ")
    transcript.save("rick.srt")
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

from utmax._version import __version__
from utmax.client import Client
from utmax.errors import (
    AgeRestricted,
    FailedToCreateConsentCookie,
    InvalidOption,
    InvalidVideoId,
    IpBlocked,
    NetworkError,
    NoTranscriptFound,
    NotTranslatable,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    TranslationLanguageNotAvailable,
    UnsupportedFormat,
    UTMaxError,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeError,
    YouTubeRequestFailed,
)
from utmax.models import (
    FormatName,
    Language,
    Segment,
    Track,
    TrackList,
    Transcript,
    VideoInfo,
    Word,
)

__all__ = [
    "AgeRestricted",
    "Client",
    "FailedToCreateConsentCookie",
    "FormatName",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "Language",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "PoTokenRequired",
    "RequestBlocked",
    "Segment",
    "Track",
    "TrackList",
    "Transcript",
    "TranscriptsDisabled",
    "TranslationLanguageNotAvailable",
    "UTMaxError",
    "UnsupportedFormat",
    "VideoInfo",
    "VideoUnavailable",
    "VideoUnplayable",
    "Word",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
    "__version__",
    "fetch",
    "list_tracks",
    "video_info",
]

logging.getLogger("utmax").addHandler(logging.NullHandler())

_default_client: Client | None = None
_default_lock = threading.Lock()


def _client() -> Client:
    """The shared default client, created on first use (thread-safe)."""
    global _default_client  # noqa: PLW0603
    client = _default_client
    if client is None:
        with _default_lock:
            if _default_client is None:
                _default_client = Client()
            client = _default_client
    return client


def fetch(
    video: str,
    languages: Sequence[str] | str | None = None,
    *,
    include_manual: bool = True,
    include_generated: bool = True,
    preserve_formatting: bool = False,
    youtube_translation: str | None = None,
) -> Transcript:
    """Fetch the best subtitle track of a video.

    Args:
        video: a video ID or any YouTube URL (watch, youtu.be, shorts, live, embed …).
        languages: language codes in order of preference, e.g. ``["tr", "en"]``; ``de`` also
            matches ``de-DE``. By default the video's spoken language is used.
        include_manual: consider subtitles written by people.
        include_generated: consider YouTube's auto-generated subtitles.
        preserve_formatting: keep ``<b>``, ``<i>`` and ``<u>`` tags.
        youtube_translation: ask YouTube to machine-translate the chosen track (best effort,
            often rate-limited; AI translation arrives in a later release).

    Manual subtitles win over auto-generated ones, and YouTube's translation is never used
    unless you ask for it.

    Raises:
        InvalidVideoId: ``video`` holds no video ID (checked before any request).
        NoTranscriptFound: no track matches ``languages`` or the filters; lists what exists.
        TranscriptsDisabled: the video has no subtitles.
        VideoUnavailable, VideoUnplayable, AgeRestricted: YouTube will not serve the video.
        RequestBlocked, IpBlocked: YouTube is blocking or rate-limiting this IP address.
        NetworkError: the network failed after retries.
    """
    return _client().fetch(
        video,
        languages,
        include_manual=include_manual,
        include_generated=include_generated,
        preserve_formatting=preserve_formatting,
        youtube_translation=youtube_translation,
    )


def list_tracks(video: str) -> TrackList:
    """Every subtitle track of a video, in YouTube's order."""
    return _client().list_tracks(video)


def video_info(video: str) -> VideoInfo:
    """Title, channel and duration of a video."""
    return _client().video_info(video)
