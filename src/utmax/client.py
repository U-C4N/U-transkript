"""The Client: configuration plus one connection pipeline that every call goes through."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterable, Sequence
from functools import partial
from typing import Any, Self

from utmax.adapters.http import RetryingTransport, UrllibTransport, open_stream
from utmax.adapters.innertube import InnerTubeClient
from utmax.adapters.providers import Translator, create_translator
from utmax.core.bilingual import bilingual
from utmax.core.downloads import DEFAULT_CHUNK_SIZE
from utmax.errors import InvalidOption
from utmax.models import (
    BulkReport,
    BulkResult,
    CollectionKind,
    Container,
    DownloadResult,
    FormatName,
    Progress,
    Quality,
    SubtitleMode,
    TrackList,
    Transcript,
    VideoEntry,
    VideoInfo,
    VideoList,
)
from utmax.services.bulk import DEFAULT_DOWNLOAD_NAME, DEFAULT_TRANSCRIPT_NAME, BulkService
from utmax.services.collections import CollectionService
from utmax.services.download import DownloadOptions, DownloadService
from utmax.services.transcripts import TranscriptService
from utmax.services.translation import translate
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
        force_ipv4: connect over IPv4 only; try it when downloads fail with StreamForbidden on a
            machine with both IPv4 and IPv6, because stream URLs are bound to one address.
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
        force_ipv4: bool = False,
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
        if transport is not None and force_ipv4:
            raise InvalidOption(
                "force_ipv4 applies to utmax's own HTTP stack; configure IPv4 in your transport."
            )
        if transport is None:
            transport = RetryingTransport(
                UrllibTransport(proxy=proxy, timeout=timeout, force_ipv4=force_ipv4),
                retries=retries,
            )
        self._transport = transport
        innertube = InnerTubeClient(transport, block_retries=block_retries)
        self._transcripts = TranscriptService(innertube)
        self._downloads = DownloadService(
            innertube, self._transcripts, partial(open_stream, transport)
        )
        self._collections = CollectionService(innertube)
        self._bulk = BulkService(self._transcripts, self._downloads)

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

    def translator(self, model: str, **options: Any) -> Translator:
        """The translator for ``"provider=model-id"``; see :func:`utmax.translator`."""
        return create_translator(model, **options)

    def translate(
        self,
        transcript: Transcript,
        to: str,
        *,
        model: str | Translator,
        instructions: str | None = None,
        resegment: bool | None = None,
        **options: Any,
    ) -> Transcript:
        """Translate ``transcript`` with an AI model; see :func:`utmax.translate`."""
        return translate(
            transcript,
            to,
            model=model,
            instructions=instructions,
            resegment=resegment,
            **options,
        )

    def bilingual(
        self, original: Transcript, translation: Transcript, *, translation_first: bool = False
    ) -> Transcript:
        """Combine a transcript and its translation; see :func:`utmax.bilingual`."""
        return bilingual(original, translation, translation_first=translation_first)

    def download(
        self,
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
        """Download a video or its audio; see :func:`utmax.download`."""
        options = DownloadOptions(
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
        return self._downloads.download(video, path, options)

    def list_videos(
        self, source: str, *, kind: CollectionKind | None = None, limit: int | None = None
    ) -> VideoList:
        """The videos of a playlist or channel; see :func:`utmax.list_videos`."""
        return self._collections.list_videos(source, kind=kind, limit=limit)

    def fetch_many(
        self,
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
        """Fetch the transcripts of many videos; see :func:`utmax.fetch_many`."""
        return self._bulk.fetch_many(
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
        self,
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
        """Fetch and translate many transcripts; see :func:`utmax.translate_many`."""
        return self._bulk.translate_many(
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
        self,
        videos: Iterable[str | VideoEntry],
        out_dir: str | os.PathLike[str],
        *,
        format: Container = "mp4",
        quality: Quality = "compat",
        subtitles: Sequence[str] | None = None,
        subtitle_mode: SubtitleMode = "embed",
        concurrency: int = 2,
        skip_existing: bool = True,
        filename: str = DEFAULT_DOWNLOAD_NAME,
        ffmpeg: str | os.PathLike[str] | None = None,
        progress: Callable[[BulkResult[DownloadResult]], None] | None = None,
    ) -> BulkReport[DownloadResult]:
        """Download many videos into a folder; see :func:`utmax.download_many`."""
        return self._bulk.download_many(
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

    def close(self) -> None:
        """Release resources; utmax keeps no open connections today, so this does nothing yet."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
