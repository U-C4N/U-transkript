"""Immutable data types shared by every layer of utmax.

``models`` is the shared data kernel: ``utmax.core`` imports it, so this module imports
``utmax.core`` only inside methods (never at module level) to avoid import cycles.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Generic, Literal, Protocol, TypeVar, overload

from utmax.errors import NotTranslatable, TranslationLanguageNotAvailable

__all__ = [
    "BulkReport",
    "BulkResult",
    "BulkStatus",
    "Codec",
    "CollectionKind",
    "Container",
    "DownloadResult",
    "Format",
    "FormatName",
    "Language",
    "Progress",
    "ProgressPhase",
    "Quality",
    "Segment",
    "SubtitleMode",
    "Track",
    "TrackFetcher",
    "TrackList",
    "Transcript",
    "VideoEntry",
    "VideoInfo",
    "VideoList",
    "Word",
]

FormatName = Literal["txt", "srt", "vtt", "json", "pretty"]
Container = Literal["mp4", "mov", "m4a", "mp3"]
Quality = Literal["compat", "max"]
SubtitleMode = Literal["embed", "sidecar", "both"]
ProgressPhase = Literal["downloading", "muxing", "converting", "finished"]
Codec = Literal["h264", "av1", "vp9", "aac", "he-aac", "opus", "other"]
CollectionKind = Literal["all", "videos", "shorts", "live"]
BulkStatus = Literal["ok", "skipped", "failed", "not_attempted"]

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Word:
    """One timed word of an auto-generated track."""

    text: str
    start: float


@dataclass(frozen=True, slots=True)
class Segment:
    """One caption cue: ``text`` shown from ``start`` for ``duration`` seconds."""

    start: float
    duration: float
    text: str
    words: tuple[Word, ...] = ()

    @property
    def end(self) -> float:
        """When the cue disappears, in seconds."""
        return self.start + self.duration


@dataclass(frozen=True, slots=True)
class VideoInfo:
    """Basic facts about a video."""

    video_id: str
    title: str
    channel: str
    channel_id: str
    duration: float
    is_live_content: bool

    @property
    def url(self) -> str:
        """The canonical watch URL."""
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True, slots=True)
class Language:
    """A language YouTube can translate a track into."""

    code: str
    name: str


class TrackFetcher(Protocol):
    """Downloads a track; implemented by the transcripts service."""

    def fetch_track(self, track: Track, *, preserve_formatting: bool) -> Transcript: ...


@dataclass(frozen=True, slots=True)
class Track:
    """One subtitle track of a video, as listed by YouTube."""

    video: VideoInfo
    language_code: str
    language: str
    is_generated: bool
    is_translatable: bool
    vss_id: str = ""
    translation_of: str | None = None
    _url: str = field(default="", repr=False, compare=False)
    _translation_languages: tuple[Language, ...] = field(default=(), repr=False, compare=False)
    _fetcher: TrackFetcher | None = field(default=None, repr=False, compare=False)

    @property
    def video_id(self) -> str:
        """The ID of the video this track belongs to."""
        return self.video.video_id

    def fetch(self, *, preserve_formatting: bool = False) -> Transcript:
        """Download this track.

        Args:
            preserve_formatting: keep ``<b>``, ``<i>`` and ``<u>`` tags instead of plain text.
        """
        if self._fetcher is None:
            raise RuntimeError(
                "This Track is not bound to a client; get tracks from utmax.list_tracks()."
            )
        return self._fetcher.fetch_track(self, preserve_formatting=preserve_formatting)

    def translate(self, language_code: str) -> Track:
        """This track machine-translated by YouTube (``tlang``).

        Best effort only: YouTube rate-limits these requests heavily. The track list's
        ``translation_languages`` is checked when YouTube provided one.
        """
        from utmax.core.captions import set_query_param

        if not self.is_translatable:
            raise NotTranslatable(
                f"YouTube cannot translate the {self.language_code} track of {self.video_id}.",
                video_id=self.video_id,
            )
        names = {language.code: language.name for language in self._translation_languages}
        if names and language_code not in names:
            raise TranslationLanguageNotAvailable(
                f"YouTube cannot translate video {self.video_id} into {language_code!r}.",
                available=tuple(names),
                video_id=self.video_id,
            )
        return replace(
            self,
            language_code=language_code,
            language=names.get(language_code, language_code),
            is_generated=True,
            is_translatable=False,
            vss_id="",
            translation_of=self.language_code,
            _url=set_query_param(self._url, "tlang", language_code),
        )


@dataclass(frozen=True, slots=True)
class TrackList(Sequence[Track]):
    """All subtitle tracks of a video, in YouTube's order.

    ``spoken_language`` is the language of the video's original audio when YouTube marks it,
    which it does for videos with dubbed audio tracks (``None`` otherwise).
    """

    video: VideoInfo
    tracks: tuple[Track, ...]
    translation_languages: tuple[Language, ...] = ()
    spoken_language: str | None = None

    @overload
    def __getitem__(self, index: int) -> Track: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[Track, ...]: ...
    def __getitem__(self, index: int | slice) -> Track | tuple[Track, ...]:
        return self.tracks[index]

    def __len__(self) -> int:
        return len(self.tracks)

    def __iter__(self) -> Iterator[Track]:
        return iter(self.tracks)

    @property
    def manual(self) -> tuple[Track, ...]:
        """Tracks written by people."""
        return tuple(track for track in self.tracks if not track.is_generated)

    @property
    def generated(self) -> tuple[Track, ...]:
        """Tracks produced by YouTube's speech recognition."""
        return tuple(track for track in self.tracks if track.is_generated)

    def find(
        self,
        languages: Sequence[str] | str | None = None,
        *,
        include_manual: bool = True,
        include_generated: bool = True,
    ) -> Track:
        """Pick the best track; see :func:`utmax.core.selection.select_track` for the rules."""
        from utmax.core.selection import select_track

        return select_track(
            self.tracks,
            languages,
            include_manual=include_manual,
            include_generated=include_generated,
            spoken_language=self.spoken_language,
        )


@dataclass(frozen=True, slots=True)
class Transcript(Sequence[Segment]):
    """A timed transcript: the segments of one track, or of a translation of one."""

    video: VideoInfo
    language_code: str
    language: str
    is_generated: bool
    segments: tuple[Segment, ...]
    translated_from: str | None = None
    translator: str | None = None
    source: Transcript | None = field(default=None, repr=False, compare=False)

    @overload
    def __getitem__(self, index: int) -> Segment: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[Segment, ...]: ...
    def __getitem__(self, index: int | slice) -> Segment | tuple[Segment, ...]:
        return self.segments[index]

    def __len__(self) -> int:
        return len(self.segments)

    def __iter__(self) -> Iterator[Segment]:
        return iter(self.segments)

    @property
    def text(self) -> str:
        """All text, whitespace-collapsed and joined with single spaces."""
        return " ".join(
            " ".join(segment.text.split()) for segment in self.segments if segment.text.strip()
        )

    @property
    def is_bilingual(self) -> bool:
        """True for bilingual transcripts such as ``en+tr``."""
        return "+" in self.language_code

    def to_dicts(self) -> list[dict[str, str | float]]:
        """``[{"text", "start", "duration"}, ...]`` like youtube-transcript-api's ``to_raw_data()``."""
        return [
            {"text": segment.text, "start": segment.start, "duration": segment.duration}
            for segment in self.segments
        ]

    def to(self, format: FormatName) -> str:
        """Render as ``"srt"``, ``"vtt"``, ``"json"``, ``"txt"`` or ``"pretty"``."""
        from utmax.core.formats import render

        return render(self, format)

    def to_srt(self) -> str:
        """SubRip text."""
        from utmax.core.formats import to_srt

        return to_srt(self.segments)

    def to_vtt(self) -> str:
        """WebVTT text."""
        from utmax.core.formats import to_vtt

        return to_vtt(self.segments)

    def to_json(self, *, indent: int | None = 2) -> str:
        """JSON with the metadata and every segment."""
        from utmax.core.formats import to_json

        return to_json(self, indent=indent)

    def to_text(self, *, separator: str = " ") -> str:
        """Plain text, segments joined by ``separator``."""
        from utmax.core.formats import to_text

        return to_text(self.segments, separator=separator)

    def to_pretty(self) -> str:
        """``[MM:SS] text`` lines (``[HH:MM:SS]`` for videos longer than an hour)."""
        from utmax.core.formats import to_pretty

        return to_pretty(self.segments)

    def save(self, path: str | os.PathLike[str], format: FormatName | None = None) -> Path:
        """Write the transcript to ``path``; the extension picks the format unless ``format`` is set.

        Works the same for originals, translations and bilingual transcripts. The file is UTF-8
        with ``\\n`` line endings and is replaced atomically.
        """
        from utmax.adapters.files import write_text_atomic
        from utmax.core.formats import format_for_path, render

        return write_text_atomic(path, render(self, format_for_path(path, format)))

    def merge_sentences(self) -> Transcript:
        """A copy whose cues are regrouped into sentences (best for auto-generated tracks)."""
        from utmax.core.segmentation import merge_sentences

        return replace(self, segments=merge_sentences(self.segments), source=None)


@dataclass(frozen=True, slots=True)
class Format:
    """One stream YouTube offers for a video; its URL never leaves utmax."""

    itag: int
    kind: Literal["video", "audio"]
    container: Literal["mp4", "webm"]
    codec: Codec
    codecs: str
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    bitrate: int = 0
    content_length: int | None = None
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    is_default_audio: bool = True
    is_drc: bool = False
    last_modified: str = ""

    @property
    def label(self) -> str:
        """A short description such as ``"137 mp4 h264 1080p25"`` or ``"140 mp4 aac 44.1kHz"``."""
        words = [str(self.itag), self.container, self.codec]
        if self.kind == "video":
            side = min((n for n in (self.width, self.height) if n), default=0)
            words.append(f"{side}p{self.fps or ''}")
        else:
            if self.audio_sample_rate:
                words.append(f"{self.audio_sample_rate / 1000:g}kHz")
            if self.is_drc:
                words.append("drc")
        return " ".join(words)


@dataclass(frozen=True, slots=True)
class Progress:
    """How far a download has come; passed to ``download(progress=...)`` callbacks."""

    video_id: str
    phase: ProgressPhase
    bytes_done: int
    bytes_total: int | None
    speed_bps: float | None = None
    eta_seconds: float | None = None

    @property
    def fraction(self) -> float | None:
        """``bytes_done / bytes_total`` between 0 and 1; ``None`` while the total is unknown."""
        if not self.bytes_total:
            return None
        return min(1.0, self.bytes_done / self.bytes_total)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """What :func:`utmax.download` produced."""

    path: Path
    video: VideoInfo
    container: Container
    video_format: Format | None
    audio_format: Format
    embedded_subtitles: tuple[str, ...] = ()
    sidecars: tuple[Path, ...] = ()
    size_bytes: int = 0
    resumed: bool = False


@dataclass(frozen=True, slots=True)
class VideoEntry:
    """One video of a playlist or channel, as :func:`utmax.list_videos` lists it."""

    video_id: str
    title: str
    duration: float | None
    channel: str
    channel_id: str
    index: int

    @property
    def url(self) -> str:
        """The canonical watch URL."""
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True, slots=True)
class VideoList(Sequence[VideoEntry]):
    """The videos of a playlist or channel, in YouTube's order.

    ``source_id`` is the playlist that was listed: the playlist's own ID, or for a channel
    the list YouTube keeps of its uploads (``UU...``, ``UULF...``, ``UUSH...``, ``UULV...``).
    ``video_count`` is the number of videos YouTube says the playlist has (it can include
    private videos, which are not listed); ``None`` when YouTube does not say.
    """

    title: str
    source_id: str
    kind: CollectionKind
    video_count: int | None
    entries: tuple[VideoEntry, ...]

    @overload
    def __getitem__(self, index: int) -> VideoEntry: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[VideoEntry, ...]: ...
    def __getitem__(self, index: int | slice) -> VideoEntry | tuple[VideoEntry, ...]:
        return self.entries[index]

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[VideoEntry]:
        return iter(self.entries)


@dataclass(frozen=True, slots=True)
class BulkResult(Generic[T]):
    """What happened to one video of ``fetch_many``, ``translate_many`` or ``download_many``.

    ``status`` is ``"ok"`` (``value`` holds the result, ``path`` the file written, if any),
    ``"skipped"`` (``path`` is the file that already existed; ``None`` for a video listed
    twice), ``"failed"`` (``error`` says why) or ``"not_attempted"`` (the run stopped first).
    """

    video_id: str
    status: BulkStatus
    value: T | None = None
    path: Path | None = None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class BulkReport(Sequence[BulkResult[T]], Generic[T]):
    """Every result of a bulk call, in the order the videos were given."""

    results: tuple[BulkResult[T], ...]

    @overload
    def __getitem__(self, index: int) -> BulkResult[T]: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[BulkResult[T], ...]: ...
    def __getitem__(self, index: int | slice) -> BulkResult[T] | tuple[BulkResult[T], ...]:
        return self.results[index]

    def __len__(self) -> int:
        return len(self.results)

    def __iter__(self) -> Iterator[BulkResult[T]]:
        return iter(self.results)

    @property
    def ok(self) -> tuple[BulkResult[T], ...]:
        """The videos that succeeded."""
        return self._with("ok")

    @property
    def skipped(self) -> tuple[BulkResult[T], ...]:
        """The videos whose file already existed (or that were listed twice)."""
        return self._with("skipped")

    @property
    def failed(self) -> tuple[BulkResult[T], ...]:
        """The videos that failed; each result's ``error`` says why."""
        return self._with("failed")

    @property
    def not_attempted(self) -> tuple[BulkResult[T], ...]:
        """The videos never tried because the run stopped (YouTube blocked it, for example)."""
        return self._with("not_attempted")

    def raise_for_errors(self) -> None:
        """Raise the error of the first failed video; do nothing when none failed."""
        for result in self.results:
            if result.error is not None:
                raise result.error

    def _with(self, status: BulkStatus) -> tuple[BulkResult[T], ...]:
        return tuple(result for result in self.results if result.status == status)
