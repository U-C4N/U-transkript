"""Immutable data types shared by every layer of utmax.

``models`` is the shared data kernel: ``utmax.core`` imports it, so this module imports
``utmax.core`` only inside methods (never at module level) to avoid import cycles.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, overload

__all__ = [
    "FormatName",
    "Language",
    "Segment",
    "Track",
    "TrackFetcher",
    "TrackList",
    "Transcript",
    "VideoInfo",
    "Word",
]

FormatName = Literal["txt", "srt", "vtt", "json", "pretty"]


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


@dataclass(frozen=True, slots=True)
class TrackList(Sequence[Track]):
    """All subtitle tracks of a video, in YouTube's order."""

    video: VideoInfo
    tracks: tuple[Track, ...]
    translation_languages: tuple[Language, ...] = ()

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
