"""Render transcripts as SRT, WebVTT, JSON, plain text or timestamped ("pretty") text."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from os import PathLike
from pathlib import PurePath

from utmax.errors import UnsupportedFormat
from utmax.models import FormatName, Segment, Transcript

__all__ = [
    "EXTENSIONS",
    "FORMATS",
    "format_for_path",
    "render",
    "to_json",
    "to_pretty",
    "to_srt",
    "to_text",
    "to_vtt",
]

FORMATS: tuple[FormatName, ...] = ("srt", "vtt", "json", "txt", "pretty")
EXTENSIONS: dict[str, FormatName] = {".srt": "srt", ".vtt": "vtt", ".json": "json", ".txt": "txt"}

_ALLOWED_VTT_TAG = re.compile(r"&lt;(/?)([biu])&gt;")


@dataclass(frozen=True, slots=True)
class _Cue:
    start_ms: int
    end_ms: int
    text: str


def format_for_path(path: str | PathLike[str], explicit: str | None = None) -> FormatName:
    """Pick the output format: ``explicit`` wins, otherwise the file extension decides."""
    if explicit is not None:
        if explicit not in FORMATS:
            raise UnsupportedFormat(
                f"Unknown format {explicit!r}; choose one of: {', '.join(FORMATS)}."
            )
        return explicit
    pure = PurePath(path)
    fmt = EXTENSIONS.get(pure.suffix.lower())
    if fmt is None:
        raise UnsupportedFormat(
            f"Cannot tell the subtitle format from the file name {pure.name!r}."
        )
    return fmt


def render(transcript: Transcript, fmt: str) -> str:
    """Render ``transcript`` in ``fmt``, one of :data:`FORMATS`."""
    name = format_for_path("", fmt)
    if name == "json":
        return to_json(transcript)
    return _SEGMENT_RENDERERS[name](transcript.segments)


def to_srt(segments: Sequence[Segment]) -> str:
    """SubRip: numbered cues with ``HH:MM:SS,mmm`` times."""
    blocks = [
        f"{index}\n{_clock(cue.start_ms, ',')} --> {_clock(cue.end_ms, ',')}\n{cue.text}\n"
        for index, cue in enumerate(_cues(segments), start=1)
    ]
    return "\n".join(blocks)


def to_vtt(segments: Sequence[Segment]) -> str:
    """WebVTT with escaped text; ``<b>``, ``<i>`` and ``<u>`` tags survive."""
    blocks = [
        f"{_clock(cue.start_ms, '.')} --> {_clock(cue.end_ms, '.')}\n{_vtt_text(cue.text)}\n"
        for cue in _cues(segments)
    ]
    return "WEBVTT\n\n" + "\n".join(blocks)


def to_json(transcript: Transcript, *, indent: int | None = 2) -> str:
    """JSON with the video, language and translation metadata plus every segment."""
    video = transcript.video
    payload = {
        "video": {
            "video_id": video.video_id,
            "title": video.title,
            "channel": video.channel,
            "channel_id": video.channel_id,
            "duration": video.duration,
            "is_live_content": video.is_live_content,
        },
        "language_code": transcript.language_code,
        "language": transcript.language,
        "is_generated": transcript.is_generated,
        "translated_from": transcript.translated_from,
        "translator": transcript.translator,
        "segments": [
            {"start": segment.start, "duration": segment.duration, "text": segment.text}
            for segment in transcript.segments
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"


def to_text(segments: Sequence[Segment], *, separator: str = " ") -> str:
    """Plain text: each segment whitespace-collapsed, joined by ``separator``."""
    parts = [" ".join(segment.text.split()) for segment in segments if segment.text.strip()]
    return separator.join(parts) + "\n" if parts else ""


def to_pretty(segments: Sequence[Segment]) -> str:
    """One ``[MM:SS] text`` line per segment; ``[HH:MM:SS]`` once the video passes an hour."""
    visible = [segment for segment in segments if segment.text.strip()]
    if not visible:
        return ""
    with_hours = max(segment.start for segment in visible) >= 3600
    lines: list[str] = []
    for segment in visible:
        stamp = _stamp(segment.start, with_hours=with_hours)
        text_lines = _lines(segment.text)
        lines.append(f"{stamp} {text_lines[0]}")
        indent = " " * (len(stamp) + 1)
        lines.extend(f"{indent}{line}" for line in text_lines[1:])
    return "\n".join(lines) + "\n"


def _cues(segments: Sequence[Segment]) -> list[_Cue]:
    timed = sorted(
        (
            (
                round(segment.start * 1000),
                round(segment.duration * 1000),
                "\n".join(_lines(segment.text)),
            )
            for segment in segments
            if segment.text.strip()
        ),
        key=lambda item: item[0],
    )
    merged: list[tuple[int, int, str]] = []
    for start, duration, text in timed:
        end = start + duration
        if merged and merged[-1][0] == start:
            _, previous_end, previous_text = merged[-1]
            merged[-1] = (start, max(previous_end, end), f"{previous_text}\n{text}")
        else:
            merged.append((start, end, text))
    cues: list[_Cue] = []
    for index, (start, end, text) in enumerate(merged):
        if index + 1 < len(merged):
            end = min(end, merged[index + 1][0])  # noqa: PLW2901
        if end > start:
            cues.append(_Cue(start, end, text))
    return cues


def _lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def _clock(milliseconds: int, separator: str) -> str:
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def _stamp(seconds: float, *, with_hours: bool) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if with_hours:
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"


def _vtt_text(text: str) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _ALLOWED_VTT_TAG.sub(r"<\1\2>", escaped)


_SEGMENT_RENDERERS: dict[str, Callable[[Sequence[Segment]], str]] = {
    "srt": to_srt,
    "vtt": to_vtt,
    "txt": to_text,
    "pretty": to_pretty,
}
