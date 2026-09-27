"""Immutable data types shared by every layer of utmax.

``models`` is the shared data kernel: ``utmax.core`` imports it, so this module imports
``utmax.core`` only inside methods (never at module level) to avoid import cycles.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Protocol, overload

from utmax.errors import NotTranslatable, TranslationLanguageNotAvailable

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
