"""The utmax MCP server: YouTube transcripts, AI translation, playlists and downloads as tools.

Every tool returns structured output. A utmax error becomes a tool error that reads
``"<message> Suggestion: <what to do>"``, so the model can explain it or try again.
"""

from __future__ import annotations

import glob
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Coroutine, Hashable, Iterator
from contextlib import contextmanager
from functools import partial
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

from utmax import Client, Translator, __version__
from utmax.core.ids import parse_video_id
from utmax.errors import UTMaxError
from utmax.mcp.config import Config
from utmax.models import (
    CollectionKind,
    Container,
    FormatName,
    Progress,
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
    "TranslationOut",
    "VideoEntryOut",
    "VideoOut",
    "VideosOut",
    "build_server",
    "download_file",
]

log = logging.getLogger("utmax.mcp")

INSTRUCTIONS = (
    "Tools for YouTube videos, given as URLs or 11-character video IDs: list a video's subtitle "
    "tracks, get its transcript (plain text, SRT, WebVTT, JSON or timestamped lines), translate "
    "a transcript with an AI model while keeping its timing, list the videos of a playlist or "
    "channel, and download a video or its audio into the server's download folder. Read long "
    "transcripts in parts with max_chars and next_offset."
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
ToArg = Annotated[str, Field(description="The target language code, such as tr or pt-BR.")]
ModelArg = Annotated[
    str | None,
    Field(
        description=(
            "The model as provider=model-id (claude, openai, gemini or openrouter), such as "
            "claude=claude-opus-5. Default: the server's UTMAX_MODEL."
        )
    ),
]
InstructionsArg = Annotated[
    str | None, Field(description="Extra guidance for the translator, such as a glossary.")
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
            "language for videos, none for audio; [] adds none."
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


class TranslationOut(TranscriptOut):
    translated_from: str | None = Field(description="The language code of the source track.")
    translator: str | None = Field(description="The model that translated, provider=model-id.")


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
    """The MCP server with utmax's five tools, using ``client`` (by default one built from
    ``config``) and ``config`` (by default read from the environment)."""
    settings = config if config is not None else Config.from_env()
    youtube = client if client is not None else Client(proxy=settings.proxy)
    reader = _Reader(youtube, settings)
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

    @server.tool(annotations=reads)
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

    @server.tool(annotations=reads)
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

    @server.tool(annotations=reads)
    def translate_transcript(
        video: VideoArg,
        to: ToArg,
        *,
        model: ModelArg = None,
        languages: LanguagesArg = None,
        format: FormatArg = "txt",
        bilingual: Annotated[
            bool, Field(description="Show each original line above its translation.")
        ] = False,
        instructions: InstructionsArg = None,
        offset: OffsetArg = 0,
        max_chars: MaxCharsArg = None,
    ) -> TranslationOut:
        """Translate the transcript of a YouTube video with an AI model, keeping its timing."""
        spec = model or settings.model
        if spec is None:
            raise ToolError(
                "No translation model is configured. Suggestion: pass model as "
                "provider=model-id (for example claude=claude-opus-5), or set UTMAX_MODEL in "
                "the MCP server's environment."
            )
        with tool_errors():
            original, translation = reader.translation(
                video, to, spec, languages=languages, instructions=instructions
            )
            result = youtube.bilingual(original, translation) if bilingual else translation
            page = transcript_out(result, format, offset, max_chars)
        return TranslationOut(
            **page.model_dump(),
            translated_from=result.translated_from,
            translator=result.translator,
        )

    @server.tool(annotations=reads)
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

    @server.tool(annotations=writes)
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
            report=partial(_report, ctx),
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
    report: Callable[[Progress], Coroutine[Any, Any, None]] | None = None,
) -> DownloadOut:
    """Download ``video`` into ``directory`` on a worker thread, unless it is already there.

    The worker also looks for the file, so a folder that cannot be searched is a tool error
    like any other file system error. ``report`` receives the download's progress on the event
    loop. When the caller is cancelled, the download stops and keeps its partial files, so the
    next call resumes it.
    """
    with tool_errors():
        video_id = parse_video_id(video)
    token = anyio.lowlevel.current_token()
    cancel = threading.Event()

    def forward(update: Progress) -> None:
        if report is None:
            return
        try:
            anyio.from_thread.run(report, update, token=token)
        except Exception:  # progress is best effort; it must never stop a download
            log.debug("could not report download progress", exc_info=True)

    def work() -> DownloadOut:
        existing = _existing_download(directory, video_id, format)
        if existing is not None:
            return DownloadOut(
                path=str(existing),
                size_bytes=existing.stat().st_size,
                video_id=video_id,
                title=existing.name.removesuffix(f" [{video_id}].{format}"),
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
        raise ToolError(str(error)) from error


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


def _page(text: str, offset: int, max_chars: int | None) -> tuple[str, int | None]:
    if max_chars is None or offset + max_chars >= len(text):
        return text[offset:], None
    end = offset + max_chars
    cut = max(text.rfind("\n", offset, end), text.rfind(" ", offset, end))
    if cut > offset:
        end = cut + 1
    return text[offset:end], end


def _existing_download(directory: Path, video_id: str, container: Container) -> Path | None:
    pattern = "*" + glob.escape(f"[{video_id}].{container}")
    return next(iter(sorted(directory.glob(pattern))), None) if directory.is_dir() else None


def _video(info: VideoInfo) -> VideoOut:
    return VideoOut(
        video_id=info.video_id,
        title=info.title,
        channel=info.channel,
        channel_id=info.channel_id,
        duration_seconds=info.duration,
        url=info.url,
    )


async def _report(ctx: Context[Any, Any], update: Progress) -> None:
    await ctx.report_progress(update.bytes_done, update.bytes_total, _progress_message(update))


def _progress_message(update: Progress) -> str:
    if update.phase != "downloading":
        return update.phase
    done = f"{update.bytes_done / 1_000_000:.1f}"
    if update.bytes_total is None:
        return f"downloading: {done} MB"
    return f"downloading: {done} of {update.bytes_total / 1_000_000:.1f} MB"


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
    """Fetches and translates transcripts for the tools, remembering the latest ones.

    A tool call keeps no state, so a long transcript or translation is read in parts, one call
    per part. The reader keeps what those calls share (the captions, the translators and the
    translations), so that a part costs no request and no model run, and every part is cut from
    the same text even though a model words its answer differently each time it is asked.
    """

    def __init__(self, client: Client, config: Config) -> None:
        self._client = client
        self._config = config
        self._transcripts = _Memory[Transcript](_MEMORY_SIZE)
        self._translators = _Memory[Translator](_MEMORY_SIZE)
        self._translations = _Memory[tuple[Transcript, Transcript]](_MEMORY_SIZE)

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

    def translation(
        self,
        video: str,
        to: str,
        model: str,
        *,
        languages: list[str] | None,
        instructions: str | None,
    ) -> tuple[Transcript, Transcript]:
        """The transcript of ``video`` and its translation into ``to`` by ``model``.

        The model runs only when this translation was not made lately. A model that cannot be
        used (a malformed spec, an unknown provider, a missing SDK or, except for Claude, a
        missing API key) is reported before any request, because the translator is made before
        the captions are fetched.
        """
        video_id = parse_video_id(video)
        wanted = None if languages is None else tuple(languages)
        key = (video_id, wanted, to, model, instructions)
        made = self._translations.get(key)
        if made is None:
            translator = self._translator(model)
            original = self.transcript(video_id, languages)
            translation = self._client.translate(
                original, to, model=translator, instructions=instructions
            )
            made = (original, translation)
            self._translations.put(key, made)
        return made

    def _translator(self, model: str) -> Translator:
        translator = self._translators.get(model)
        if translator is None:
            translator = self._client.translator(model, **self._config.translator_options(model))
            self._translators.put(model, translator)
        return translator
