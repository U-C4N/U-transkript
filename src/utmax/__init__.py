"""u-transcript max: YouTube transcripts, AI translation and downloads with zero dependencies.

Quick start::

    import utmax

    transcript = utmax.fetch("https://youtu.be/dQw4w9WgXcQ")
    transcript.save("rick.srt")

    turkish = utmax.translate(transcript, "tr", model="claude=claude-opus-5")
    utmax.bilingual(transcript, turkish).save("rick.en+tr.srt")

    utmax.download("dQw4w9WgXcQ", "rick.mp4")  # H.264 + AAC + English subtitles

    videos = utmax.list_videos("@RickAstleyYT", kind="videos", limit=20)
    utmax.fetch_many(videos, out_dir="subs")  # one .srt per video
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from utmax._version import __version__
from utmax.client import Client
from utmax.core.downloads import DEFAULT_CHUNK_SIZE
from utmax.errors import (
    AgeRestricted,
    CollectionNotFound,
    CollectionUnavailable,
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
    InvalidSource,
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
    BulkReport,
    BulkResult,
    CollectionKind,
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
    VideoEntry,
    VideoInfo,
    VideoList,
    Word,
)
from utmax.providers import Translator
from utmax.services.bulk import DEFAULT_DOWNLOAD_NAME, DEFAULT_TRANSCRIPT_NAME

__all__ = [
    "AgeRestricted",
    "BulkReport",
    "BulkResult",
    "Client",
    "CollectionKind",
    "CollectionNotFound",
    "CollectionUnavailable",
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
    "InvalidSource",
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
    "VideoEntry",
    "VideoInfo",
    "VideoList",
    "VideoUnavailable",
    "VideoUnplayable",
    "Word",
    "YouTubeDataUnparsable",
    "YouTubeError",
    "YouTubeRequestFailed",
    "__version__",
    "bilingual",
    "download",
    "download_many",
    "fetch",
    "fetch_many",
    "list_tracks",
    "list_videos",
    "translate",
    "translate_many",
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
    quality: Quality = "best",
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
        utmax.download("dQw4w9WgXcQ", "videos/")  # the best MP4 (AV1 up to 8K), named by title
        utmax.download("dQw4w9WgXcQ", "rick.mp4", subtitles=[english, turkish])

    Args:
        video: a video ID or any YouTube URL.
        path: the output file; its extension picks the type (``.mp4``, ``.mov``, ``.m4a``,
            ``.mp3``). A folder (an existing one, or a path ending with ``/``) gets
            ``"{title} [{video_id}].{ext}"``.
        format: the file type when ``path`` is a folder or has no extension; it must match the
            extension otherwise.
        quality: ``"best"`` (the largest picture the file type holds: AV1 or H.264 in
            ``.mp4``, HDR where it is the only way to a larger picture; H.264 in ``.mov``) or
            ``"compat"`` (H.264 up to 1080p, plays everywhere).
        subtitles: language codes and/or transcripts (translations and bilingual ones too).
            ``None`` embeds the spoken-language track in videos and adds nothing to audio;
            ``[]`` adds none. Codes are chosen like :func:`fetch`, never with YouTube's own
            translation.
        subtitle_mode: ``"embed"`` (toggleable tracks in the video), ``"sidecar"`` (``.srt``
            files next to it) or ``"both"``; audio files always get sidecar files.
        default_subtitle: the language code of the embedded track shown by default (else the
            first one).
        connections: parallel connections, 1 to 16.
        chunk_size: bytes per range request, at least 256 KiB (YouTube slows down larger
            requests of 8 MiB, so the default is 2 MiB).
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
        InvalidVideoId, InvalidOption, UnsupportedFormat: bad arguments, before any request
            (subtitle problems, such as a ``default_subtitle`` that is not embedded, before any
            media byte).
        OutputExists: the file or a subtitle file exists and ``overwrite`` is false.
        FFmpegNotFound: ``.mp3`` without a usable ffmpeg (before any request).
        NoTranscriptFound: a requested subtitle language does not exist (before any media byte).
        FormatNotAvailable: no stream fits the type and quality (live streams, for example).
        StreamForbidden, DownloadIncomplete, NetworkError: the download failed; call again to
            resume.
        PoTokenRequired: YouTube serves only the start of this video's streams without a
            proof-of-origin token, which utmax cannot create.
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


def list_videos(
    source: str, *, kind: CollectionKind | None = None, limit: int | None = None
) -> VideoList:
    """The videos of a playlist or a channel, in YouTube's order.

    Examples::

        videos = utmax.list_videos("https://www.youtube.com/playlist?list=PL...")
        shorts = utmax.list_videos("https://www.youtube.com/@RickAstleyYT/shorts")
        latest = utmax.list_videos("@RickAstleyYT", kind="videos", limit=50)
        report = utmax.fetch_many(videos, out_dir="subs")

    Args:
        source: a playlist URL or ID, a channel URL (``/@handle``, ``/channel/UC...``,
            ``/c/name``, ``/user/name``), an ``@handle`` or a channel ID.
        kind: for channels, ``"all"`` uploads, long-form ``"videos"``, ``"shorts"`` or past
            ``"live"`` streams. By default a channel link's tab chooses (``/videos``,
            ``/shorts``, ``/streams``), and a link without one lists every upload. Playlists
            are always listed whole.
        limit: stop after this many videos; ``None`` lists everything (at most 1000 pages).

    Each :class:`VideoEntry` has the video ID, title, duration (``None`` when YouTube does not
    show one), channel and its 1-based position. Private and deleted videos are left out and a
    video listed twice appears once. A channel without Shorts or live streams gives an empty
    list for those kinds.

    utmax lists a playlist with the ANDROID_VR client, which lists all of it, and lists it once
    more with the WEB client when ANDROID_VR fails. WEB shows at most 100 Shorts of a channel
    and hides an occasional video, so a listing that fell back to WEB can hold fewer videos
    than ``VideoList.video_count``. A listing that ends by itself (not at ``limit``) before that
    count is returned as it is, and a warning on the ``utmax.youtube`` logger says so:
    ``listed 100 of the 297 videos YouTube counts; the list may be incomplete``.

    Raises:
        InvalidSource: ``source`` names no playlist or channel (checked before any request).
        InvalidOption: ``kind`` or ``limit`` is invalid, or ``kind`` was given for a playlist.
        CollectionUnavailable: a Mix (``RD...``) or another playlist YouTube will not list.
        CollectionNotFound: the playlist or channel does not exist or is private.
        RequestBlocked, IpBlocked: YouTube is blocking or rate-limiting this IP address.
        NetworkError: the network failed after retries.
    """
    return _client().list_videos(source, kind=kind, limit=limit)


def fetch_many(
    videos: Iterable[str | VideoEntry],
    *,
    out_dir: str | os.PathLike[str] | None = None,
    format: FormatName = "srt",
    languages: Sequence[str] | str | None = None,
    include_manual: bool = True,
    include_generated: bool = True,
    concurrency: int = 4,
    skip_existing: bool = True,
    filename: str = DEFAULT_TRANSCRIPT_NAME,
    progress: Callable[[BulkResult[Transcript]], None] | None = None,
) -> BulkReport[Transcript]:
    """Fetch the transcripts of many videos, optionally saving each one as a file.

    Example::

        report = utmax.fetch_many(utmax.list_videos("@RickAstleyYT", limit=20), out_dir="subs")
        print(len(report.ok), "saved,", len(report.failed), "failed")

    Args:
        videos: video IDs, URLs and/or entries of a :func:`list_videos` result.
        out_dir: the folder for the files (created when missing); ``None`` keeps the
            transcripts in memory only (``result.value``).
        format: ``"srt"``, ``"vtt"``, ``"json"``, ``"txt"`` or ``"pretty"`` (saved as ``.txt``).
        languages: language codes in order of preference, chosen per video as in
            :func:`fetch`; ``include_manual`` and ``include_generated`` work as there too.
        concurrency: how many videos are fetched at the same time, 1 to 16.
        skip_existing: skip a video, without any request, when ``out_dir`` already holds its
            file: a name the template gives with its video ID, whatever the title, channel and
            ``{index}`` (a new upload shifts every position in a channel listing) or, without
            ``languages``, the language (a file in another language than ``languages`` asks
            for does not count).
        filename: the file-name template. Fields: ``{video_id}`` (required), ``{title}``,
            ``{channel}``, ``{index}`` (the position in ``videos``, or in the listing for
            :class:`VideoEntry` items), ``{language_code}`` and ``{ext}``. Format specs such
            as ``{index:03d}`` work.
        progress: called with each video's :class:`BulkResult` as soon as it is known, never
            in parallel. An exception it raises stops the run like Ctrl-C and propagates, with
            no report.

    The :class:`BulkReport` holds one result per video, in the order given: ``"ok"``,
    ``"skipped"``, ``"failed"`` (with its ``error``) or ``"not_attempted"``. A failure never
    stops the other videos, except that when YouTube blocks the IP address the videos not
    started yet are not attempted. ``report.raise_for_errors()`` raises the first failure.

    Raises:
        InvalidOption, UnsupportedFormat: bad arguments (before any request).
        KeyboardInterrupt: Ctrl-C; videos not started yet are dropped.
    """
    return _client().fetch_many(
        videos,
        out_dir=out_dir,
        format=format,
        languages=languages,
        include_manual=include_manual,
        include_generated=include_generated,
        concurrency=concurrency,
        skip_existing=skip_existing,
        filename=filename,
        progress=progress,
    )


def translate_many(
    videos: Iterable[str | VideoEntry],
    to: str,
    *,
    model: str | Translator,
    out_dir: str | os.PathLike[str] | None = None,
    format: FormatName = "srt",
    languages: Sequence[str] | str | None = None,
    bilingual: bool = False,
    instructions: str | None = None,
    resegment: bool | None = None,
    concurrency: int = 2,
    skip_existing: bool = True,
    filename: str = DEFAULT_TRANSCRIPT_NAME,
    progress: Callable[[BulkResult[Transcript]], None] | None = None,
    **options: Any,
) -> BulkReport[Transcript]:
    """Fetch the transcripts of many videos and translate them with one AI translator.

    Example::

        videos = utmax.list_videos("@RickAstleyYT", limit=20)
        utmax.translate_many(videos, "tr", model="claude=claude-opus-5", out_dir="subs")

    Args:
        videos: video IDs, URLs and/or entries of a :func:`list_videos` result.
        to: the target language code, such as ``"tr"``.
        model: ``"provider=model-id"`` or a :class:`~utmax.providers.Translator`, as in
            :func:`translate`.
        out_dir, format, concurrency, skip_existing, filename, progress: as in
            :func:`fetch_many`; ``{language_code}`` is the target language, or
            ``"<source>+<target>"`` (such as ``"en+tr"``) with ``bilingual``.
        languages: the source track, chosen per video as in :func:`fetch`.
        bilingual: return (and save) bilingual transcripts, the original line on top.
        instructions, resegment: as in :func:`translate`.
        **options: passed to :func:`translator` when ``model`` is a string.

    The same translator serves every video. ``concurrency`` counts videos; each video's cues
    are translated in up to the translator's own ``concurrency`` batches at a time (set it with
    :func:`translator`, for example ``utmax.translator(model, concurrency=2)``). Besides a
    block by YouTube, a rejected API key stops the run: the videos not started yet are then
    ``"not_attempted"``. Ctrl-C waits for the translations already running to finish.

    Raises:
        InvalidOption, InvalidModelSpec, UnsupportedFormat: bad arguments (before any request).
        ProviderNotInstalled, ProviderAuthError: the translator cannot be created.
        KeyboardInterrupt: Ctrl-C; videos not started yet are dropped.
    """
    return _client().translate_many(
        videos,
        to,
        model=model,
        out_dir=out_dir,
        format=format,
        languages=languages,
        bilingual=bilingual,
        instructions=instructions,
        resegment=resegment,
        concurrency=concurrency,
        skip_existing=skip_existing,
        filename=filename,
        progress=progress,
        **options,
    )


def download_many(
    videos: Iterable[str | VideoEntry],
    out_dir: str | os.PathLike[str],
    *,
    format: Container = "mp4",
    quality: Quality = "best",
    subtitles: Sequence[str] | None = None,
    subtitle_mode: SubtitleMode = "embed",
    concurrency: int = 2,
    skip_existing: bool = True,
    filename: str = DEFAULT_DOWNLOAD_NAME,
    ffmpeg: str | os.PathLike[str] | None = None,
    progress: Callable[[BulkResult[DownloadResult]], None] | None = None,
) -> BulkReport[DownloadResult]:
    """Download many videos, or their audio, into one folder.

    Example::

        videos = utmax.list_videos("@RickAstleyYT", kind="videos")
        utmax.download_many(videos, "rick", format="m4a")

    Args:
        videos: video IDs, URLs and/or entries of a :func:`list_videos` result.
        out_dir: the folder for the files (created when missing).
        format, quality, subtitles, subtitle_mode, ffmpeg: as in :func:`download`, for every
            video; ``subtitles`` takes language codes only.
        concurrency: how many videos are downloaded at the same time, 1 to 16 (each with four
            connections).
        skip_existing: skip a video, without any request, when ``out_dir`` already holds its
            file; ``False`` downloads it again and replaces the file. Interrupted downloads
            resume either way.
        filename: the file-name template, as in :func:`fetch_many` but without
            ``{language_code}``; the default is ``"{title} [{video_id}].{ext}"``.
        progress: called with each video's :class:`BulkResult` as soon as it is known; an
            exception it raises stops the run (running downloads keep their ``.part`` files).

    The :class:`BulkReport` works as for :func:`fetch_many`; each ``value`` is the video's
    :class:`DownloadResult`.

    Raises:
        InvalidOption, UnsupportedFormat: bad arguments (before any request).
        FFmpegNotFound: ``format="mp3"`` without a usable ffmpeg (before any request).
        KeyboardInterrupt: Ctrl-C; running downloads stop and keep their ``.part`` files.
    """
    return _client().download_many(
        videos,
        out_dir,
        format=format,
        quality=quality,
        subtitles=subtitles,
        subtitle_mode=subtitle_mode,
        concurrency=concurrency,
        skip_existing=skip_existing,
        filename=filename,
        ffmpeg=ffmpeg,
        progress=progress,
    )
