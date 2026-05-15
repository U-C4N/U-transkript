from __future__ import annotations

import json
from abc import ABC, abstractmethod


def _split_hms(seconds: float) -> tuple[int, int, int, int]:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        secs += 1
        millis = 0
    return hours, minutes, secs, millis


def _format_clock(seconds: float, include_hours: bool = False) -> str:
    hours, minutes, secs, _ = _split_hms(seconds)
    if include_hours or hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_subtitle_timestamp(seconds: float, ms_separator: str) -> str:
    hours, minutes, secs, millis = _split_hms(seconds)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{ms_separator}{millis:03d}"


class Formatter(ABC):
    """Base class for transcript formatters."""

    @abstractmethod
    def format_transcript(self, transcript: list[dict], **kwargs) -> str:
        ...


class PrettyPrintFormatter(Formatter):
    """Human-readable transcript with optional timestamps and line wrapping."""

    def format_transcript(self, transcript: list[dict], **kwargs) -> str:
        show_timestamps = kwargs.get("show_timestamps", True)
        max_chars_per_line = kwargs.get("max_chars_per_line", 80)

        lines: list[str] = []
        for entry in transcript:
            text = entry["text"]
            line = f"[{_format_clock(entry['start'])}] {text}" if show_timestamps else text

            if max_chars_per_line and len(line) > max_chars_per_line:
                lines.extend(self._wrap_text(line, max_chars_per_line))
            else:
                lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current: list[str] = []
        current_len = 0

        for word in words:
            extra = len(word) + (1 if current else 0)
            if current and current_len + extra > max_chars:
                lines.append(" ".join(current))
                current = [word]
                current_len = len(word)
            else:
                current.append(word)
                current_len += extra

        if current:
            lines.append(" ".join(current))
        return lines


class JSONFormatter(Formatter):
    """JSON array of transcript entries."""

    def format_transcript(self, transcript: list[dict], **kwargs) -> str:
        indent = kwargs.get("indent", 2)
        ensure_ascii = kwargs.get("ensure_ascii", False)
        return json.dumps(transcript, indent=indent, ensure_ascii=ensure_ascii)


class TextFormatter(Formatter):
    """Plain text: just the entries joined with a separator."""

    def format_transcript(self, transcript: list[dict], **kwargs) -> str:
        separator = kwargs.get("separator", " ")
        return separator.join(entry["text"] for entry in transcript)


class SRTFormatter(Formatter):
    """SubRip (.srt) subtitle format."""

    def format_transcript(self, transcript: list[dict], **kwargs) -> str:
        entries: list[str] = []
        for i, entry in enumerate(transcript, 1):
            start = _format_subtitle_timestamp(entry["start"], ",")
            end = _format_subtitle_timestamp(entry["start"] + entry["duration"], ",")
            entries.append(f"{i}\n{start} --> {end}\n{entry['text']}\n")
        return "\n".join(entries)


class VTTFormatter(Formatter):
    """WebVTT (.vtt) subtitle format."""

    def format_transcript(self, transcript: list[dict], **kwargs) -> str:
        parts: list[str] = ["WEBVTT\n"]
        for entry in transcript:
            start = _format_subtitle_timestamp(entry["start"], ".")
            end = _format_subtitle_timestamp(entry["start"] + entry["duration"], ".")
            parts.append(f"{start} --> {end}\n{entry['text']}\n")
        return "\n".join(parts)


_FORMATTERS: dict[str, type[Formatter]] = {
    "pretty": PrettyPrintFormatter,
    "json": JSONFormatter,
    "text": TextFormatter,
    "srt": SRTFormatter,
    "vtt": VTTFormatter,
}


def get_formatter(formatter_name: str) -> Formatter:
    """Return a formatter instance by name (case-insensitive)."""
    name = formatter_name.lower()
    if name not in _FORMATTERS:
        raise ValueError(
            f"Unknown formatter: {formatter_name}. Available: {list(_FORMATTERS)}"
        )
    return _FORMATTERS[name]()
