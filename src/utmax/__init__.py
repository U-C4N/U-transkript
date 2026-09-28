"""u-transcript max: YouTube transcripts, AI translation and downloads with zero dependencies.

Quick start::

    import utmax

    transcript = utmax.fetch("https://youtu.be/dQw4w9WgXcQ")
    transcript.save("rick.srt")

    turkish = utmax.translate(transcript, "tr", model="claude=claude-opus-5")
    utmax.bilingual(transcript, turkish).save("rick.en+tr.srt")

    utmax.download("dQw4w9WgXcQ", "rick.mp4")  # H.264 + AAC + English subtitles
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Sequence
from typing import Any

from utmax._version import __version__
from utmax.client import Client
from utmax.core.downloads import DEFAULT_CHUNK_SIZE
from utmax.errors import (
    AgeRestricted,
    DownloadCancelled,
    DownloadError,
    DownloadIncomplete,
    FailedToCreateConsentCookie,
    FFmpegError,
    FFmpegFailed,
    FFmpegNotFound,
    FormatNotAvailable,
    InvalidModelSpec,
    InvalidOption,
    InvalidVideoId,
    IpBlocked,
    MissingExtra,
    MuxError,
    NetworkError,
    NoTranscriptFound,
    NotTranslatable,
    OutputExists,
    PoTokenRequired,
    ProviderAuthError,
    ProviderError,
    ProviderNotInstalled,
    ProviderRateLimited,
    RequestBlocked,
    StreamForbidden,
    TranscriptsDisabled,
    TranslationError,
    TranslationLanguageNotAvailable,
    TranslationMismatch,
    TranslationRefused,
    UnsupportedFormat,
    UTMaxError,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeError,
    YouTubeRequestFailed,
)
from utmax.models import (
    Container,
    DownloadResult,
    Format,
    FormatName,
    Language,
    Progress,
    Quality,
    Segment,
    SubtitleMode,
    Track,
    TrackList,
    Transcript,
    VideoInfo,
    Word,
)
from utmax.providers import Translator

__all__ = [
    "AgeRestricted",
    "Client",
    "Container",
    "DownloadCancelled",
    "DownloadError",
    "DownloadIncomplete",
    "DownloadResult",
    "FFmpegError",
    "FFmpegFailed",
    "FFmpegNotFound",
    "FailedToCreateConsentCookie",
    "Format",
    "FormatName",
    "FormatNotAvailable",
    "InvalidModelSpec",
    "InvalidOption",
    "InvalidVideoId",
    "IpBlocked",
    "Language",
    "MissingExtra",
    "MuxError",
    "NetworkError",
    "NoTranscriptFound",
    "NotTranslatable",
    "OutputExists",
    "PoTokenRequired",
    "Progress",
    "ProviderAuthError",
    "ProviderError",
    "ProviderNotInstalled",
    "ProviderRateLimited",
    "RequestBlocked",
    "Segment",
    "StreamForbidden",
    "Track",
    "TrackList",
    "Transcript",
    "TranscriptsDisabled",
    "TranslationError",
    "TranslationLanguageNotAvailable",
    "TranslationMismatch",
    "TranslationRefused",
    "Translator",
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
    "bilingual",
    "download",
    "fetch",
    "list_tracks",
    "translate",
    "translator",
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
            often rate-limited; :func:`translate` translates with AI instead).

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


def translator(model: str, **options: Any) -> Translator:
    """The AI translator for ``model``, written ``"provider=model-id"``.

    Providers: ``claude`` (Anthropic), ``openai`` (OpenAI, or any OpenAI-compatible server via
    ``base_url``), ``gemini`` (Google) and ``openrouter``. There is no default model::

        utmax.translator("claude=claude-opus-5", effort="low")
        utmax.translator("openai=llama3.1:8b", base_url="http://localhost:11434/v1")  # Ollama

    Args:
        model: ``"provider=model-id"``; only the first ``=`` separates the two parts.
        **options: provider options (``api_key``, ``effort``, ``max_tokens``, ``base_url``,
            ``json_mode``, ``app_name``, ``retry_attempts``, ``client``) and engine options
            (``batch_chars``, ``batch_items``, ``context_items``, ``concurrency``,
            ``max_attempts``); see :mod:`utmax.providers`.

    Raises:
        InvalidModelSpec: ``model`` is not ``"provider=model-id"`` with a known provider.
        InvalidOption: an option is out of range, or ``base_url`` is used without ``openai``.
        ProviderNotInstalled: the provider's SDK is missing; the message names the extra.
        ProviderAuthError: no API key was found.
    """
    return _client().translator(model, **options)


def translate(
    transcript: Transcript,
    to: str,
    *,
    model: str | Translator,
    instructions: str | None = None,
    resegment: bool | None = None,
    **options: Any,
) -> Transcript:
    """Translate a transcript with AI, keeping every timing.

    Example::

        turkish = utmax.translate(transcript, "tr", model="claude=claude-opus-5")
        turkish.save("rick.tr.srt")

    Args:
        transcript: the transcript to translate, usually from :func:`fetch`.
        to: the target language code, such as ``"tr"``, ``"de"`` or ``"pt-BR"``.
        model: ``"provider=model-id"`` (see :func:`translator`) or a
            :class:`~utmax.providers.Translator`.
        instructions: extra guidance for the model, e.g. ``"Use informal Turkish."``.
        resegment: merge cues into sentences before translating; by default only
            auto-generated transcripts are merged.
        **options: passed to :func:`translator` when ``model`` is a string.

    The result keeps the source timings and records ``translated_from``, ``translator`` and
    the exact ``source`` cues; every format works for it, and :func:`bilingual` combines it
    with the original. A result is returned only when every cue was translated.

    Raises:
        InvalidOption: ``to`` is not a language code, the transcript is bilingual, or options
            were given together with a Translator instance.
        TranslationMismatch: the model kept returning unusable answers for a cue.
        TranslationRefused: the model or its safety system declined the content.
        ProviderAuthError, ProviderRateLimited, ProviderError: the provider failed.
    """
    return _client().translate(
        transcript,
        to,
        model=model,
        instructions=instructions,
        resegment=resegment,
        **options,
    )


def bilingual(
    original: Transcript, translation: Transcript, *, translation_first: bool = False
) -> Transcript:
    """One transcript showing both languages: the original line on top, the translation below.

    Example::

        utmax.bilingual(transcript, turkish).save("rick.en+tr.vtt")

    ``translation_first=True`` puts the translation on top. The language code is
    ``"<original>+<translation>"`` (``"en+tr"``) and every format works for the result.

    Raises:
        InvalidOption: one of the transcripts is already bilingual.
    """
    return _client().bilingual(original, translation, translation_first=translation_first)


def download(
    video: str,
    path: str | os.PathLike[str],
    *,
    format: Container | None = None,
    quality: Quality = "compat",
    subtitles: Sequence[str | Transcript] | None = None,
    subtitle_mode: SubtitleMode = "embed",
    default_subtitle: str | None = None,
    connections: int = 4,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    resume: bool = True,
    overwrite: bool = False,
    ffmpeg: str | os.PathLike[str] | None = None,
    progress: Callable[[Progress], None] | None = None,
    cancel: threading.Event | None = None,
) -> DownloadResult:
    """Download a video (``.mp4``, ``.mov``) or its audio (``.m4a``, ``.mp3``) with subtitles.

    Examples::

        utmax.download("dQw4w9WgXcQ", "rick.mp4")  # H.264 up to 1080p, AAC, English subtitles
        utmax.download("dQw4w9WgXcQ", "rick.m4a")  # audio only; no ffmpeg needed
        utmax.download("dQw4w9WgXcQ", "videos/", quality="max")  # AV1 up to 4K, named by title
        utmax.download("dQw4w9WgXcQ", "rick.mp4", subtitles=[english, turkish])

    Args:
        video: a video ID or any YouTube URL.
        path: the output file; its extension picks the type (``.mp4``, ``.mov``, ``.m4a``,
            ``.mp3``). A folder (an existing one, or a path ending with ``/``) gets
            ``"{title} [{video_id}].{ext}"``.
        format: the file type when ``path`` is a folder or has no extension; it must match the
            extension otherwise.
        quality: ``"compat"`` (H.264 up to 1080p, plays everywhere) or ``"max"`` (AV1 or
            H.264 up to 2160p; ``.mp4`` only).
        subtitles: language codes and/or transcripts (translations and bilingual ones too).
            ``None`` embeds the spoken-language track in videos and adds nothing to audio;
            ``[]`` adds none. Codes are chosen like :func:`fetch`, never with YouTube's own
            translation.
        subtitle_mode: ``"embed"`` (toggleable tracks in the video), ``"sidecar"`` (``.srt``
            files next to it) or ``"both"``; audio files always get sidecar files.
        default_subtitle: the language code of the embedded track shown by default (else the
            first one).
        connections: parallel connections, 1 to 16.
        chunk_size: bytes per range request, at least 256 KiB.
        resume: continue an interrupted download from its ``.part`` files.
        overwrite: replace existing files instead of raising :class:`OutputExists`.
        ffmpeg: the ffmpeg executable for ``.mp3`` (default: ``$UTMAX_FFMPEG``, then ``PATH``).
        progress: called with a :class:`Progress` at most four times a second, never in
            parallel; keep it quick. An exception it raises stops the download.
        cancel: set this event to stop; the ``.part`` files stay, so a new call resumes.

    Streams are downloaded into ``<file>.<itag>.part`` files next to the target and then
    combined, so the disk briefly holds about twice the file size; the parts are deleted only
    after success. Stream URLs work only from the IP address that requested them, so do not
    switch proxies or VPNs during a download.

    Raises:
        InvalidVideoId, InvalidOption, UnsupportedFormat: bad arguments (before any request).
        OutputExists: the file or a subtitle file exists and ``overwrite`` is false.
        FFmpegNotFound: ``.mp3`` without a usable ffmpeg (before any request).
        NoTranscriptFound: a requested subtitle language does not exist (before any media byte).
        FormatNotAvailable: no stream fits the type and quality (live streams, for example).
        StreamForbidden, DownloadIncomplete, NetworkError: the download failed; call again to
            resume.
        DownloadCancelled: ``cancel`` was set.
        MuxError, FFmpegFailed: the file could not be assembled.
        VideoUnavailable, VideoUnplayable, AgeRestricted, RequestBlocked: YouTube refused.
    """
    return _client().download(
        video,
        path,
        format=format,
        quality=quality,
        subtitles=subtitles,
        subtitle_mode=subtitle_mode,
        default_subtitle=default_subtitle,
        connections=connections,
        chunk_size=chunk_size,
        resume=resume,
        overwrite=overwrite,
        ffmpeg=ffmpeg,
        progress=progress,
        cancel=cancel,
    )
