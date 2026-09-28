"""3GPP timed text (``tx3g``) subtitle tracks, the format FFmpeg calls ``mov_text``.

A sample is a 16-bit big-endian byte length followed by UTF-8 text (``"\\n"`` between lines).
Samples cover the timeline without holes: the time between cues is an empty sample. The
sample description is FFmpeg's ``mov_text`` default (libavcodec/movtextenc.c): centred at the
bottom, transparent background, font 1 at 18 points in opaque white; its font table names
"Sans-Serif" (FFmpeg's own default name is "Serif").
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from utmax.core.languages import english_name, iso639_2t
from utmax.core.media.boxes import box, u8, u16, u32
from utmax.errors import InvalidOption, MuxError
from utmax.models import Segment, Transcript

__all__ = [
    "TIMESCALE",
    "Cue",
    "SubtitleTrack",
    "decode_sample",
    "default_subtitle_index",
    "encode_sample",
    "normalize_cues",
    "sample_entry",
    "subtitle_track",
    "track_languages",
    "track_name",
]

TIMESCALE = 1000
_MAX_TEXT_BYTES = 0xFFFF
_FONT = b"Sans-Serif"
_FORMATTING_TAG = re.compile(r"</?[biu]>")
_LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*")


@dataclass(frozen=True, slots=True)
class Cue:
    """One subtitle shown from ``start`` to ``end`` (milliseconds)."""

    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class SubtitleTrack:
    """A tx3g track ready to mux: labels plus ``(duration_ms, payload)`` samples."""

    code: str
    name: str
    language: str
    tag: str
    samples: tuple[tuple[int, bytes], ...]


def normalize_cues(segments: Sequence[Segment]) -> tuple[Cue, ...]:
    """Millisecond cues timed exactly like the SRT and WebVTT output of ``utmax.core.formats``.

    Blank segments are skipped and each line is whitespace-collapsed; cues are sorted by start,
    cues that start together are merged, every cue ends no later than the next one starts,
    and cues left without duration are dropped.
    """
    timed: list[tuple[int, int, str]] = []
    for segment in segments:
        lines = [" ".join(line.split()) for line in segment.text.splitlines() if line.strip()]
        if lines:
            start = round(segment.start * 1000)
            timed.append((start, start + round(segment.duration * 1000), "\n".join(lines)))
    timed.sort(key=lambda cue: cue[0])
    merged: list[tuple[int, int, str]] = []
    for start, end, text in timed:
        if merged and merged[-1][0] == start:
            merged[-1] = (start, max(merged[-1][1], end), f"{merged[-1][2]}\n{text}")
        else:
            merged.append((start, end, text))
    cues: list[Cue] = []
    for index, (start, end, text) in enumerate(merged):
        stop = min(end, merged[index + 1][0]) if index + 1 < len(merged) else end
        if stop > start:
            cues.append(Cue(start, stop, text))
    return tuple(cues)


def encode_sample(text: str) -> bytes:
    """A tx3g sample: 16-bit length plus UTF-8 text, cut at a character boundary at 64 KiB."""
    data = text.encode("utf-8")
    if len(data) > _MAX_TEXT_BYTES:
        data = data[:_MAX_TEXT_BYTES].decode("utf-8", errors="ignore").encode("utf-8")
    return u16(len(data)) + data


def decode_sample(payload: bytes) -> str:
    """The text of a tx3g sample (the inverse of :func:`encode_sample`)."""
    if len(payload) < 2 or len(payload) < 2 + int.from_bytes(payload[:2], "big"):
        raise MuxError("A tx3g sample is shorter than its length field says.")
    return payload[2 : 2 + int.from_bytes(payload[:2], "big")].decode("utf-8", errors="replace")


def sample_entry() -> bytes:
    """The ``tx3g`` sample description (FFmpeg's ``mov_text`` default, font "Sans-Serif")."""
    font_table = box("ftab", u16(1), u16(1), u8(len(_FONT)), _FONT)
    return box(
        "tx3g",
        bytes(6),  # reserved
        u16(1),  # data reference index
        u32(0),  # display flags
        b"\x01\xff",  # justification: horizontally centred, vertically at the bottom
        bytes(4),  # background colour (RGBA): transparent
        bytes(8),  # default text box: top, left, bottom, right
        u16(0) + u16(0),  # style record: first and last character
        u16(1) + u8(0) + u8(18),  # font ID 1, regular face, 18 points
        b"\xff\xff\xff\xff",  # text colour (RGBA): opaque white
        font_table,
    )


def track_name(transcript: Transcript) -> str:
    """The track title players show, e.g. ``"Turkish (AI: claude=...)"`` or ``"English + Turkish"``."""
    label = transcript.language.strip() or " + ".join(
        english_name(part) or part for part in transcript.language_code.split("+")
    )
    if transcript.translator and not transcript.is_bilingual:
        return f"{label} (AI: {transcript.translator})"
    return label


def track_languages(code: str) -> tuple[str, str]:
    """``(ISO 639-2/T code for mdhd, BCP-47 tag for elng)``; bilingual codes become ``mul``."""
    if "+" in code:
        return "mul", "mul"
    tag = code.strip().replace("_", "-")
    return iso639_2t(tag), (tag if _LANGUAGE_TAG.fullmatch(tag) else "und")


def subtitle_track(transcript: Transcript, *, limit: int | None = None) -> SubtitleTrack:
    """The tx3g track of ``transcript``; with ``limit`` (ms) no cue runs past it.

    ``<b>``/``<i>``/``<u>`` tags are removed. A transcript without cues becomes one empty sample
    lasting ``limit`` (at least 1 ms), so the requested track still exists.
    """
    cues = normalize_cues(transcript.segments)
    if limit is not None:
        cues = tuple(Cue(c.start, min(c.end, limit), c.text) for c in cues if c.start < limit)
    timeline: list[tuple[int, str]] = []
    position = 0
    for cue in cues:
        if cue.start > position:
            timeline.append((cue.start - position, ""))
        timeline.append((cue.end - cue.start, _FORMATTING_TAG.sub("", cue.text)))
        position = cue.end
    if not timeline:
        timeline.append((max(limit or 0, 1), ""))
    language, tag = track_languages(transcript.language_code)
    return SubtitleTrack(
        code=transcript.language_code,
        name=track_name(transcript),
        language=language,
        tag=tag,
        samples=tuple((duration, encode_sample(text)) for duration, text in timeline),
    )


def default_subtitle_index(codes: Sequence[str], default: str | None) -> int | None:
    """The embedded subtitle track enabled by default: the one whose code is ``default``
    (case-insensitive), else the first; ``None`` when there are no subtitle tracks.

    Raises:
        InvalidOption: ``default`` matches none of ``codes``.
    """
    if default is None:
        return 0 if codes else None
    wanted = default.strip().lower()
    for index, code in enumerate(codes):
        if code.lower() == wanted:
            return index
    raise InvalidOption(
        f"default_subtitle={default!r} matches no embedded subtitle track "
        f"(embedded: {', '.join(codes) or 'none'}).",
        suggestion="Pass the language code of one of the subtitles being embedded, or None.",
    )
