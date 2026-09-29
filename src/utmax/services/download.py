"""Download a video or its audio: choose the streams, fetch them resumably, then mux them (or
convert to MP3), embedding the subtitles or writing them next to the file."""

from __future__ import annotations

import logging
import os
import secrets
import threading
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path

from utmax.adapters.downloader import Downloader, Job, Opener, ProgressReporter
from utmax.adapters.ffmpeg import FFmpeg, locate_ffmpeg
from utmax.adapters.files import (
    FileByteSource,
    replace_with_retry,
    write_mux_plan,
    write_text_atomic,
)
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.downloads import DEFAULT_CHUNK_SIZE, MIN_CHUNK_SIZE
from utmax.core.filenames import Target, part_name, resolve_target, sidecar_name
from utmax.core.ids import parse_video_id
from utmax.core.media.moov import Flavor
from utmax.core.media.mux import plan_mux
from utmax.core.media.tx3g import default_subtitle_index
from utmax.core.player import PlayerData
from utmax.core.selection import select_track
from utmax.core.streams import choose_streams
from utmax.errors import DownloadCancelled, InvalidOption, OutputExists, UTMaxError
from utmax.models import (
    Container,
    DownloadResult,
    Progress,
    Quality,
    SubtitleMode,
    TrackList,
    Transcript,
    VideoInfo,
)
from utmax.services.transcripts import TranscriptService

__all__ = ["MAX_CONNECTIONS", "DownloadOptions", "DownloadService"]

log = logging.getLogger("utmax.download")

MAX_CONNECTIONS = 16
_QUALITIES = ("compat", "max")
_SUBTITLE_MODES = ("embed", "sidecar", "both")


@dataclass(frozen=True, slots=True)
class DownloadOptions:
    """Everything :func:`utmax.download` accepts besides the video and the path.

    ``name`` names the file when ``path`` is a folder, from the video and the file extension
    (``download_many`` fills in its file-name template this way).
    """

    format: Container | None = None
    quality: Quality = "compat"
    subtitles: Sequence[str | Transcript] | None = None
    subtitle_mode: SubtitleMode = "embed"
    default_subtitle: str | None = None
    connections: int = 4
    chunk_size: int = DEFAULT_CHUNK_SIZE
    resume: bool = True
    overwrite: bool = False
    ffmpeg: str | os.PathLike[str] | None = None
    progress: Callable[[Progress], None] | None = None
    cancel: threading.Event | None = None
    name: Callable[[VideoInfo, str], str] | None = None

    def check(self) -> None:
        """Reject option values that can never work, before anything is requested."""
        if self.quality not in _QUALITIES:
            raise InvalidOption(f'quality={self.quality!r} is not "compat" or "max".')
        if self.subtitle_mode not in _SUBTITLE_MODES:
            raise InvalidOption(
                f'subtitle_mode={self.subtitle_mode!r} is not "embed", "sidecar" or "both".'
            )
        if not 1 <= self.connections <= MAX_CONNECTIONS:
            raise InvalidOption(
                f"connections must be between 1 and {MAX_CONNECTIONS}, not {self.connections}."
            )
        if self.chunk_size < MIN_CHUNK_SIZE:
            raise InvalidOption(
                f"chunk_size must be at least {MIN_CHUNK_SIZE} bytes, not {self.chunk_size}."
            )
        if isinstance(self.subtitles, (str, Transcript)):
            raise InvalidOption(
                f"subtitles must be a list, such as subtitles=[{self.subtitles!r}].",
                suggestion=f"Pass subtitles=[{self.subtitles!r}]: a list of codes or transcripts.",
            )
        if self.subtitles is not None:
            for item in self.subtitles:
                if not isinstance(item, (str, Transcript)):
                    raise InvalidOption(
                        f"Each subtitle must be a language code or a Transcript, not {item!r}."
                    )


class DownloadService:
    """The download use case: InnerTube for streams and captions, an opener for media bytes."""

    def __init__(
        self,
        innertube: InnerTubeClient,
        transcripts: TranscriptService,
        opener: Opener,
        *,
        locate: Callable[[str | os.PathLike[str] | None], str] = locate_ffmpeg,
        make_ffmpeg: Callable[[str], FFmpeg] = FFmpeg,
    ) -> None:
        self._innertube = innertube
        self._transcripts = transcripts
        self._opener = opener
        self._locate = locate
        self._make_ffmpeg = make_ffmpeg

    def download(
        self, video: str, path: str | os.PathLike[str], options: DownloadOptions
    ) -> DownloadResult:
        """Download ``video`` to ``path``; :func:`utmax.download` documents the rules.

        Every utmax error raised on the way names the video, even when it comes from a layer
        that does not know it (option checks, file names, ffmpeg, the muxer, the network).
        """
        video_id = parse_video_id(video)
        try:
            return self._download(video_id, path, options)
        except UTMaxError as error:
            if error.video_id is None:
                error.video_id = video_id
            raise

    def check(self, path: str | os.PathLike[str], options: DownloadOptions) -> None:
        """Raise what :meth:`download` would raise for ``path`` and ``options`` before its first
        request: bad options, no usable ffmpeg for ``.mp3``, an existing file."""
        self._prepare(path, _listed(options), video_id=None)

    def _download(
        self, video_id: str, path: str | os.PathLike[str], options: DownloadOptions
    ) -> DownloadResult:
        options = _listed(options)
        target, ffmpeg = self._prepare(path, options, video_id=video_id)
        container = target.container
        audio_only = container in ("m4a", "mp3")
        player = self._innertube.player(video_id, purpose="streams")
        final = Path(target.path_for(player.video, name=options.name))
        if target.file is None:
            _check_free(final, options.overwrite, video_id)
        subtitles = self._subtitles(player, options.subtitles, audio_only=audio_only)
        embedded, sidecars = _placement(
            subtitles, final, options, audio_only=audio_only, video_id=video_id
        )
        for sidecar, _ in sidecars:
            _check_free(sidecar, options.overwrite, video_id)
        video_stream, audio_stream = choose_streams(
            player.streams, container=container, quality=options.quality, video_id=video_id
        )
        streams = [stream for stream in (video_stream, audio_stream) if stream is not None]
        log.info(
            "downloading %s of %s to %s",
            " + ".join(stream.format.label for stream in streams),
            video_id,
            final.name,
        )
        jobs = [Job(stream, Path(part_name(final, stream.format.itag))) for stream in streams]
        reporter = ProgressReporter(video_id, options.progress)
        downloader = Downloader(
            self._opener,
            connections=options.connections,
            chunk_size=options.chunk_size,
            refresh=lambda: self._innertube.player(video_id, purpose="streams").streams,
            reporter=reporter,
            cancel=options.cancel,
        )
        resumed = downloader.run(jobs, video_id=video_id, resume=options.resume)
        if ffmpeg is not None:
            reporter.report("converting", 0, None, force=True)
            _convert(ffmpeg, jobs[-1].part, final, options.cancel)
        else:
            _mux(
                jobs,
                final,
                flavor=_flavor(container),
                embedded=embedded,
                options=options,
                reporter=reporter,
                video_id=video_id,
            )
        for job in jobs:
            _discard(job.part)
            _discard(job.state_path)
        written = tuple(write_text_atomic(path, t.to_srt()) for path, t in sidecars)
        size = final.stat().st_size
        reporter.report("finished", size, size, force=True)
        return DownloadResult(
            path=final,
            video=player.video,
            container=container,
            video_format=video_stream.format if video_stream is not None else None,
            audio_format=audio_stream.format,
            embedded_subtitles=tuple(transcript.language_code for transcript in embedded),
            sidecars=written,
            size_bytes=size,
            resumed=resumed,
        )

    def _prepare(
        self, path: str | os.PathLike[str], options: DownloadOptions, *, video_id: str | None
    ) -> tuple[Target, FFmpeg | None]:
        """Every check that needs no request; the target and, for ``.mp3``, ffmpeg."""
        options.check()
        target = resolve_target(path, format=options.format, is_dir=Path(path).is_dir())
        container = target.container
        if container == "mov" and options.quality == "max":
            raise InvalidOption(
                'quality="max" needs .mp4: QuickTime .mov files cannot hold AV1 video.',
                suggestion='Save max quality as .mp4, or use quality="compat" for .mov.',
                video_id=video_id,
            )
        if container in ("m4a", "mp3") and options.default_subtitle is not None:
            raise InvalidOption(
                f".{container} files cannot embed subtitles, so default_subtitle has no effect.",
                suggestion="Leave default_subtitle out for audio files.",
                video_id=video_id,
            )
        ffmpeg = self._ffmpeg(options.ffmpeg) if container == "mp3" else None
        if target.file is not None:
            _check_free(Path(target.file), options.overwrite, video_id)
        return target, ffmpeg

    def _ffmpeg(self, explicit: str | os.PathLike[str] | None) -> FFmpeg:
        tool = self._make_ffmpeg(self._locate(explicit))
        tool.check_mp3()
        return tool

    def _subtitles(
        self,
        player: PlayerData,
        requested: Sequence[str | Transcript] | None,
        *,
        audio_only: bool,
    ) -> list[Transcript]:
        """Fetch every subtitle before any media byte, so a wrong language fails fast."""
        video_id = player.video.video_id
        if requested is None:
            if audio_only:
                return []
            spoken = self._transcripts.track_list(player)
            if not spoken:
                log.info("video %s has no subtitles; downloading it without", video_id)
                return []
            return [spoken.find().fetch()]
        tracks: TrackList | None = None
        subtitles: list[Transcript] = []
        for item in requested:
            if isinstance(item, Transcript):
                if item.video.video_id != video_id:
                    raise InvalidOption(
                        f"A subtitle transcript belongs to video {item.video.video_id}, "
                        f"not {video_id}.",
                        video_id=video_id,
                    )
                subtitles.append(item)
                continue
            if tracks is None:
                tracks = self._transcripts.track_list(player)
            subtitles.append(select_track(tracks.tracks, item).fetch())
        codes = [transcript.language_code.lower() for transcript in subtitles]
        if len(set(codes)) != len(codes):
            raise InvalidOption(
                f"Each subtitle needs its own language code; got {', '.join(codes)}.",
                video_id=video_id,
            )
        return subtitles


def _placement(
    subtitles: list[Transcript],
    final: Path,
    options: DownloadOptions,
    *,
    audio_only: bool,
    video_id: str,
) -> tuple[list[Transcript], list[tuple[Path, Transcript]]]:
    """Which subtitles go into the file, and which are written next to it (and where)."""
    if audio_only:
        return [], [(Path(sidecar_name(final, t.language_code)), t) for t in subtitles]
    mode = options.subtitle_mode
    embedded = subtitles if mode in ("embed", "both") else []
    beside = subtitles if mode in ("sidecar", "both") else []
    if embedded:
        default_subtitle_index([t.language_code for t in embedded], options.default_subtitle)
    elif options.default_subtitle is not None:
        raise InvalidOption(
            "default_subtitle picks an embedded track, but no subtitles are embedded.",
            suggestion='Use subtitle_mode="embed" or "both", or leave default_subtitle out.',
            video_id=video_id,
        )
    return embedded, [(Path(sidecar_name(final, t.language_code)), t) for t in beside]


def _discard(leftover: Path) -> None:
    """Delete a finished download's part or state file; a lock (antivirus, indexer) only warns."""
    try:
        leftover.unlink(missing_ok=True)
    except OSError as error:
        log.warning("could not delete %s: %s", leftover.name, error)


def _listed(options: DownloadOptions) -> DownloadOptions:
    """``options`` with ``subtitles`` as a tuple (callers may pass any iterable)."""
    if options.subtitles is None or isinstance(options.subtitles, (str, Transcript)):
        return options
    return replace(options, subtitles=tuple(options.subtitles))


def _check_free(path: Path, overwrite: bool, video_id: str | None) -> None:
    if path.exists() and not overwrite:
        raise OutputExists(f"{path} already exists.", video_id=video_id)


def _flavor(container: Container) -> Flavor:
    if container == "mov":
        return "mov"
    if container == "m4a":
        return "m4a"
    return "mp4"


def _mux(
    jobs: Sequence[Job],
    final: Path,
    *,
    flavor: Flavor,
    embedded: Sequence[Transcript],
    options: DownloadOptions,
    reporter: ProgressReporter,
    video_id: str,
) -> None:
    """Assemble ``final`` from the parts, atomically; the parts stay when this fails."""

    def progress(written: int, total: int) -> None:
        if options.cancel is not None and options.cancel.is_set():
            raise DownloadCancelled(
                f"The download of video {video_id} was cancelled; run it again to finish it.",
                video_id=video_id,
            )
        reporter.report("muxing", written, total)

    with ExitStack() as stack:
        sources = [stack.enter_context(FileByteSource(job.part)) for job in jobs]
        plan = plan_mux(
            sources, flavor=flavor, subtitles=embedded, default_subtitle=options.default_subtitle
        )
        write_mux_plan(plan, sources, final, progress=progress)


def _convert(ffmpeg: FFmpeg, audio: Path, final: Path, cancel: threading.Event | None) -> None:
    """Convert to MP3 in a temporary file next to ``final``, then move it into place."""
    temporary = final.with_name(f".{final.name}.{secrets.token_hex(4)}.tmp")
    try:
        ffmpeg.to_mp3(audio, temporary, cancel=cancel)
        with temporary.open("rb+") as handle:
            os.fsync(handle.fileno())
        replace_with_retry(temporary, final)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
