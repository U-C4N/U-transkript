"""The utmax MCP server: YouTube transcripts, playlists and downloads as tools.

Every tool returns structured output. A utmax error becomes a tool error that reads
``"<message> Suggestion: <what to do>"``, so the model can explain it or try again. The server
calls no AI provider: the assistant that uses it translates transcripts itself, and translation
with an API key stays a feature of the library (:func:`utmax.translate`).
"""

from __future__ import annotations

import glob
import inspect
import io
import logging
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable, Coroutine, Hashable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Generic, Literal, TypeVar

import anyio
import anyio.from_thread
import anyio.lowlevel
import anyio.to_thread
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from utmax import Client, __version__
from utmax.core.ids import parse_video_id
from utmax.errors import UTMaxError
from utmax.mcp.config import Config
from utmax.models import (
    CollectionKind,
    Container,
    FormatName,
    Progress,
    ProgressPhase,
    Quality,
    SubtitleMode,
    Transcript,
    VideoInfo,
)

__all__ = [
    "DownloadOut",
    "TrackOut",
    "TracksOut",
    "TranscriptOut",
    "VideoEntryOut",
    "VideoOut",
    "VideosOut",
    "build_server",
    "download_file",
    "run",
]

log = logging.getLogger("utmax.mcp")
_F = TypeVar("_F", bound=Callable[..., Any])

INSTRUCTIONS = (
    "Tools for YouTube videos, given as URLs or 11-character video IDs: list a video's subtitle "
    "tracks, get its transcript (plain text, SRT, WebVTT, JSON or timestamped lines), list the "
    "videos of a playlist or channel, and download a video or its audio into the server's "
    "download folder. Read long transcripts in parts with max_chars and next_offset. To "
    "translate a transcript, get it as srt or vtt and translate its text lines yourself, keeping "
    "the timing lines as they are."
)

VideoArg = Annotated[str, Field(description="A YouTube video URL or 11-character video ID.")]
LanguagesArg = Annotated[
    list[str] | None,
    Field(
        description=(
            'Language codes in order of preference, such as ["de", "en"]; "de" also finds '
            '"de-DE". Default: the language spoken in the video.'
        )
    ),
]
FormatArg = Annotated[
    FormatName,
    Field(
        description=(
            "txt: plain text; srt or vtt: subtitles; json: segments with times; pretty: "
            "[MM:SS] lines."
        )
    ),
]
TrackSourceArg = Annotated[
    Literal["any", "manual", "generated"],
    Field(
        description=(
            "manual: only subtitles written by people; generated: only YouTube's automatic "
            "ones; any: manual first."
        )
    ),
]
OffsetArg = Annotated[
    int, Field(ge=0, description="Return the content from this character on (see next_offset).")
]
MaxCharsArg = Annotated[
    int | None,
    Field(
        ge=1,
        description=("Return at most this many characters (cut at a line or word end); null: all."),
    ),
]
CollectionArg = Annotated[
    str,
    Field(
        description=(
            "A playlist URL or ID, or a channel URL, @handle or channel ID; a channel link's tab "
            "(/videos, /shorts, /streams) picks the list."
        )
    ),
]
KindArg = Annotated[
    CollectionKind | None,
    Field(
        description=(
            "For channels: all uploads, videos (long-form), shorts or live (past streams). "
            "Default: the link's tab, else all."
        )
    ),
]
LimitArg = Annotated[int, Field(ge=1, le=5000, description="The most videos to list.")]
ContainerArg = Annotated[
    Container,
    Field(description="mp4 or mov: video with sound; m4a or mp3: audio only (mp3 needs ffmpeg)."),
]
QualityArg = Annotated[
    Quality,
    Field(description="compat: H.264 up to 1080p (plays everywhere); max: up to 4K (mp4 only)."),
]
SubtitlesArg = Annotated[
    list[str] | None,
    Field(
        description=(
            'Subtitle languages to add, such as ["en", "de"]. Default: the spoken '
            "language for videos, none for audio; [] adds none. Audio files (m4a, mp3) get "
            "them as .srt files next to them."
        )
    ),
]
SubtitleModeArg = Annotated[
    SubtitleMode,
    Field(description="embed: inside the video; sidecar: .srt files next to it; both: the two."),
]


class VideoOut(BaseModel):
    video_id: str
    title: str
    channel: str
    channel_id: str
    duration_seconds: float
    url: str


class TrackOut(BaseModel):
    language_code: str
    language: str
    is_generated: bool = Field(description="True for YouTube's automatic speech recognition.")
    is_translatable: bool = Field(description="True when YouTube can translate the track.")


class TracksOut(BaseModel):
    video: VideoOut
    tracks: list[TrackOut]


class TranscriptOut(BaseModel):
    video_id: str
    title: str
    language_code: str
    language: str
    is_generated: bool
    format: FormatName
    content: str
    total_chars: int = Field(description="The length of the whole content.")
    offset: int
    next_offset: int | None = Field(description="Pass it as offset to read on; null at the end.")


class VideoEntryOut(BaseModel):
    video_id: str
    title: str
    duration_seconds: float | None
    channel: str
    channel_id: str
    index: int
    url: str


class VideosOut(BaseModel):
    title: str
    source_id: str = Field(description="The playlist that was listed.")
    kind: CollectionKind
    count: int | None = Field(
        description="How many videos YouTube counts in the list (private ones included)."
    )
    videos: list[VideoEntryOut]


class DownloadOut(BaseModel):
    path: str
    size_bytes: int
    video_id: str
    title: str
    container: Container
    embedded_subtitles: list[str]
    sidecars: list[str]
    skipped: bool = Field(description="True when the file was already in the download folder.")


def build_server(client: Client | None = None, config: Config | None = None) -> MCPServer:
    """The MCP server with utmax's four tools, using ``client`` (by default one built from
    ``config``) and ``config`` (by default read from the environment)."""
    settings = config if config is not None else Config.from_env()
    youtube = client if client is not None else Client(proxy=settings.proxy)
    reader = _Reader(youtube)
    server = MCPServer(
        "utmax",
        title="u-transcript max",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://github.com/U-C4N/U-transkript",
    )
    reads = ToolAnnotations(read_only_hint=True, open_world_hint=True)
    writes = ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
    )

    def tool(annotations: ToolAnnotations) -> Callable[[_F], _F]:
        """Register a tool described by its docstring without the indentation, which Python
        3.11 and 3.12 keep in ``__doc__`` (3.13 removes it)."""

        def register(function: _F) -> _F:
            description = inspect.cleandoc(function.__doc__ or "")
            server.add_tool(function, description=description, annotations=annotations)
            return function

        return register

    @tool(reads)
    def list_tracks(video: VideoArg) -> TracksOut:
        """List the subtitle tracks of a YouTube video: language, written by people or
        generated automatically, and whether YouTube can translate it."""
        with tool_errors():
            tracks = youtube.list_tracks(video)
        return TracksOut(
            video=_video(tracks.video),
            tracks=[
                TrackOut(
                    language_code=track.language_code,
                    language=track.language,
                    is_generated=track.is_generated,
                    is_translatable=track.is_translatable,
                )
                for track in tracks
            ],
        )

    @tool(reads)
    def get_transcript(
        video: VideoArg,
        *,
        languages: LanguagesArg = None,
        format: FormatArg = "txt",
        source: TrackSourceArg = "any",
        offset: OffsetArg = 0,
        max_chars: MaxCharsArg = None,
    ) -> TranscriptOut:
        """Get the transcript (subtitles) of a YouTube video, by default in the spoken language
        with subtitles written by people preferred over automatic ones."""
        with tool_errors():
            transcript = reader.transcript(
                video,
                languages,
                include_manual=source != "generated",
                include_generated=source != "manual",
            )
            return transcript_out(transcript, format, offset, max_chars)

    @tool(reads)
    def list_videos(source: CollectionArg, kind: KindArg = None, limit: LimitArg = 50) -> VideosOut:
        """List the videos of a YouTube playlist or channel, in YouTube's order."""
        with tool_errors():
            videos = youtube.list_videos(source, kind=kind, limit=limit)
        return VideosOut(
            title=videos.title,
            source_id=videos.source_id,
            kind=videos.kind,
            count=videos.video_count,
            videos=[
                VideoEntryOut(
                    video_id=entry.video_id,
                    title=entry.title,
                    duration_seconds=entry.duration,
                    channel=entry.channel,
                    channel_id=entry.channel_id,
                    index=entry.index,
                    url=entry.url,
                )
                for entry in videos
            ],
        )

    @tool(writes)
    async def download(
        video: VideoArg,
        format: ContainerArg = "mp4",
        quality: QualityArg = "compat",
        subtitles: SubtitlesArg = None,
        subtitle_mode: SubtitleModeArg = "embed",
        *,
        ctx: Context[Any, Any],
    ) -> DownloadOut:
        """Download a YouTube video (mp4, mov) or its audio (m4a, mp3) into the server's
        download folder, named after its title. A file that is already there is not
        downloaded again."""
        return await download_file(
            youtube,
            settings.download_dir,
            video,
            format=format,
            quality=quality,
            subtitles=subtitles,
            subtitle_mode=subtitle_mode,
            report=ctx.report_progress,
        )

    return server


async def download_file(
    client: Client,
    directory: Path,
    video: str,
    *,
    format: Container = "mp4",
    quality: Quality = "compat",
    subtitles: list[str] | None = None,
    subtitle_mode: SubtitleMode = "embed",
    report: Callable[[float, float | None, str | None], Coroutine[Any, Any, None]] | None = None,
) -> DownloadOut:
    """Download ``video`` into ``directory`` on a worker thread, unless it is already there.

    The worker also looks for the file, so a folder that cannot be searched is a tool error
    like any other file system error. ``report`` receives ``(progress, total, message)`` on the
    event loop, like ``Context.report_progress``: one bar for the whole call that only fills
    (see ``_Counter``). When the caller is cancelled, the download stops and keeps its partial
    files, so the next call resumes it.
    """
    with tool_errors():
        video_id = parse_video_id(video)
    token = anyio.lowlevel.current_token()
    cancel = threading.Event()
    counter = _Counter()
    failed = False

    def forward(update: Progress) -> None:
        nonlocal failed
        if report is None or cancel.is_set():  # nobody is listening any more
            return
        counted = counter.count(update)
        if counted is None:
            return
        progress, total = counted
        try:
            anyio.from_thread.run(report, progress, total, _progress_message(update), token=token)
        except Exception:  # progress is best effort; it must never stop a download
            # The first failure of a download is a warning, so that progress which never gets
            # through (an anyio older than 4.11, say) shows in the log; the rest is debugging.
            level = logging.DEBUG if failed else logging.WARNING
            failed = True
            log.log(level, "could not report download progress", exc_info=True)

    def work() -> DownloadOut:
        existing = _existing_download(directory, video_id, format)
        if existing is not None:
            return DownloadOut(
                path=str(existing),
                size_bytes=existing.stat().st_size,
                video_id=video_id,
                title=existing.name.removesuffix(f".{format}").removesuffix(f" [{video_id}]"),
                container=format,
                embedded_subtitles=[],
                sidecars=[],
                skipped=True,
            )
        directory.mkdir(parents=True, exist_ok=True)
        # The search above already kept a finished download. What is left in the way is a
        # subtitle file of an earlier download, which this one replaces: the tool has no
        # overwrite argument for the model to follow utmax's suggestion with.
        result = client.download(
            video_id,
            directory,
            format=format,
            quality=quality,
            subtitles=subtitles,
            subtitle_mode=subtitle_mode,
            overwrite=True,
            progress=forward,
            cancel=cancel,
        )
        return DownloadOut(
            path=str(result.path),
            size_bytes=result.size_bytes,
            video_id=result.video.video_id,
            title=result.video.title,
            container=result.container,
            embedded_subtitles=list(result.embedded_subtitles),
            sidecars=[str(path) for path in result.sidecars],
            skipped=False,
        )

    try:
        with tool_errors():
            return await anyio.to_thread.run_sync(work, abandon_on_cancel=True)
    except anyio.get_cancelled_exc_class():
        cancel.set()
        raise


@contextmanager
def tool_errors() -> Iterator[None]:
    """Turn utmax errors (and file system errors) into tool errors the model can read."""
    try:
        yield
    except UTMaxError as error:
        raise ToolError(f"{error} Suggestion: {error.suggestion}") from error
    except OSError as error:
        raise ToolError(
            f"{error} Suggestion: check that UTMAX_DOWNLOAD_DIR names a folder the MCP server "
            "can create and write to."
        ) from error


def transcript_out(
    transcript: Transcript, format: FormatName, offset: int, max_chars: int | None
) -> TranscriptOut:
    """The tool output for ``transcript``: its text in ``format``, from ``offset`` on and cut
    after ``max_chars`` characters at a line or word end."""
    text = transcript.to(format)
    content, next_offset = _page(text, offset, max_chars)
    return TranscriptOut(
        video_id=transcript.video.video_id,
        title=transcript.video.title,
        language_code=transcript.language_code,
        language=transcript.language,
        is_generated=transcript.is_generated,
        format=format,
        content=content,
        total_chars=len(text),
        offset=offset,
        next_offset=next_offset,
    )


def run() -> None:
    """Serve the tools over stdio (the ``utmax-mcp`` command); logs go to stderr."""
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.from_env()
    try:
        client = Client(proxy=config.proxy)
    except UTMaxError as error:
        raise SystemExit(f"utmax-mcp: {error} Suggestion: {error.suggestion}") from error
    build_server(client, config).run("stdio")


def _page(text: str, offset: int, max_chars: int | None) -> tuple[str, int | None]:
    if max_chars is None or offset + max_chars >= len(text):
        return text[offset:], None
    end = offset + max_chars
    cut = max(text.rfind("\n", offset, end), text.rfind(" ", offset, end))
    if cut > offset:
        end = cut + 1
    return text[offset:end], end


def _existing_download(directory: Path, video_id: str, container: Container) -> Path | None:
    """A finished download of ``video_id`` as ``container`` in ``directory``: utmax names it
    ``"{title} [{video_id}].{ext}"``, or ``"{video_id}.{ext}"`` when nothing of the title is left
    for a file name."""
    if not directory.is_dir():
        return None
    named = directory.glob("* " + glob.escape(f"[{video_id}].{container}"))
    plain = directory / f"{video_id}.{container}"
    return min([*named, *([plain] if plain.is_file() else [])], default=None)


def _video(info: VideoInfo) -> VideoOut:
    return VideoOut(
        video_id=info.video_id,
        title=info.title,
        channel=info.channel,
        channel_id=info.channel_id,
        duration_seconds=info.duration,
        url=info.url,
    )


def _progress_message(update: Progress) -> str:
    if update.phase != "downloading":
        return update.phase
    done = f"{update.bytes_done / 1_000_000:.1f}"
    if update.bytes_total is None:
        return f"downloading: {done} MB"
    return f"downloading: {done} of {update.bytes_total / 1_000_000:.1f} MB"


class _Counter:
    """Turns the progress of one download into one bar that only fills.

    utmax counts every phase of a download from zero, but a client draws one bar for the call.
    The download fills the first half of it and muxing, which writes about as many bytes again,
    the second, so the total is twice the download's size from the first update that knows it;
    converting to MP3 reports no amounts and keeps the bar at half until the file is finished.
    MCP progress must grow with every notification: an update that would not move the bar on is
    left out, except the first one of a phase, which is sent one byte further so the client
    still learns of the phase.
    """

    def __init__(self) -> None:
        self._size: int | None = None
        self._sent: int | None = None
        self._phase: ProgressPhase | None = None

    def count(self, update: Progress) -> tuple[int, int | None] | None:
        """``(progress, total)`` for ``update``, or ``None`` when it would not move the bar."""
        if update.phase == "downloading" and update.bytes_total:
            self._size = update.bytes_total
        size = self._size
        total = None if size is None else 2 * size
        if update.phase == "downloading" or size is None:
            done = update.bytes_done
        elif update.phase == "finished":
            done = 2 * size
        elif update.phase == "muxing" and update.bytes_total:
            done = size + update.bytes_done * size // update.bytes_total
        else:
            done = size
        if total is not None:
            done = min(done, total)
        if self._sent is not None and done <= self._sent:
            if update.phase == self._phase:
                return None
            done = self._sent + 1
            total = None if total is None else max(total, done)
        self._sent, self._phase = done, update.phase
        return done, total


_MEMORY_SIZE = 8
_T = TypeVar("_T")


class _Memory(Generic[_T]):
    """The values used most recently, by key; safe to share between threads."""

    def __init__(self, size: int) -> None:
        self._size = size
        self._values: OrderedDict[Hashable, _T] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> _T | None:
        """The value remembered for ``key``, which counts as used, or ``None``."""
        with self._lock:
            value = self._values.get(key)
            if value is not None:
                self._values.move_to_end(key)
            return value

    def put(self, key: Hashable, value: _T) -> None:
        """Remember ``value`` for ``key``; when full, forget the value used longest ago."""
        with self._lock:
            self._values[key] = value
            self._values.move_to_end(key)
            while len(self._values) > self._size:
                self._values.popitem(last=False)


class _Reader:
    """Fetches transcripts for the tools, remembering the latest ones.

    A tool call keeps no state, so a long transcript is read in parts, one call per part. The
    reader keeps the transcripts those calls share, so that a part costs no request.
    """

    def __init__(self, client: Client) -> None:
        self._client = client
        self._transcripts = _Memory[Transcript](_MEMORY_SIZE)

    def transcript(
        self,
        video: str,
        languages: list[str] | None,
        *,
        include_manual: bool = True,
        include_generated: bool = True,
    ) -> Transcript:
        """The transcript of ``video``, fetched unless it was fetched lately."""
        video_id = parse_video_id(video)
        wanted = None if languages is None else tuple(languages)
        key = (video_id, wanted, include_manual, include_generated)
        transcript = self._transcripts.get(key)
        if transcript is None:
            transcript = self._client.fetch(
                video_id,
                languages,
                include_manual=include_manual,
                include_generated=include_generated,
            )
            self._transcripts.put(key, transcript)
        return transcript
