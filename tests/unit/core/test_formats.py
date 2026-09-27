"""Tests for the transcript renderers."""

from __future__ import annotations

import json

import pytest

from tests.helpers.builders import make_transcript
from utmax.core.formats import (
    EXTENSIONS,
    FORMATS,
    format_for_path,
    render,
    to_json,
    to_pretty,
    to_srt,
    to_text,
    to_vtt,
)
from utmax.errors import UnsupportedFormat
from utmax.models import Segment, Transcript, VideoInfo

SEGMENTS = (
    Segment(1.36, 1.68, "[♪♪♪]"),
    Segment(18.64, 3.24, "♪ We're no strangers to love ♪"),
    Segment(22.64, 4.32, "♪ You know the rules\nand so do I ♪"),
)


def test_srt_numbers_cues_and_keeps_line_breaks() -> None:
    assert to_srt(SEGMENTS) == (
        "1\n00:00:01,360 --> 00:00:03,040\n[♪♪♪]\n\n"
        "2\n00:00:18,640 --> 00:00:21,880\n♪ We're no strangers to love ♪\n\n"
        "3\n00:00:22,640 --> 00:00:26,960\n♪ You know the rules\nand so do I ♪\n"
    )


def test_overlaps_are_clamped_and_empty_or_zero_length_cues_dropped() -> None:
    segments = (
        Segment(0.0, 5.0, "a"),
        Segment(3.0, 2.0, "b"),
        Segment(4.0, 0.0, "zero"),
        Segment(6.0, 1.0, "   "),
    )
    assert to_srt(segments) == (
        "1\n00:00:00,000 --> 00:00:03,000\na\n\n2\n00:00:03,000 --> 00:00:04,000\nb\n"
    )


def test_cues_are_sorted_by_start() -> None:
    srt = to_srt((Segment(5.0, 1.0, "late"), Segment(1.0, 1.0, "early")))
    assert srt.index("early") < srt.index("late")


def test_cues_starting_together_are_merged_not_dropped() -> None:
    srt = to_srt((Segment(1.0, 2.0, "SPEAKER A: hi"), Segment(1.0, 1.0, "SPEAKER B: hello")))
    assert srt == "1\n00:00:01,000 --> 00:00:03,000\nSPEAKER A: hi\nSPEAKER B: hello\n"


def test_long_videos_get_hour_timestamps() -> None:
    assert "01:02:03,500 --> 01:02:04,750" in to_srt((Segment(3723.5, 1.25, "late"),))
    assert "01:02:03.500 --> 01:02:04.750" in to_vtt((Segment(3723.5, 1.25, "late"),))


def test_vtt_escapes_text_but_keeps_basic_styling() -> None:
    vtt = to_vtt((Segment(1.0, 2.0, "a < b & c > d"), Segment(4.0, 1.0, "<i>styled</i> -->")))
    assert vtt == (
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\na &lt; b &amp; c &gt; d\n\n"
        "00:00:04.000 --> 00:00:05.000\n<i>styled</i> --&gt;\n"
    )


def test_json_has_metadata_and_keeps_non_ascii_literal() -> None:
    transcript = make_transcript(
        Segment(0.5, 1.0, "♪ Ğüş 日本語"), language_code="tr", language="Turkish"
    )
    text = to_json(transcript)
    assert "♪ Ğüş 日本語" in text
    assert text.endswith("\n")
    data = json.loads(text)
    assert data["video"]["video_id"] == "dQw4w9WgXcQ"
    assert data["video"]["channel"] == "Rick Astley"
    assert (data["language_code"], data["language"], data["is_generated"]) == (
        "tr",
        "Turkish",
        False,
    )
    assert data["translated_from"] is None
    assert data["translator"] is None
    assert data["segments"] == [{"start": 0.5, "duration": 1.0, "text": "♪ Ğüş 日本語"}]


def test_json_keeps_non_ascii_titles_literal() -> None:
    video = VideoInfo("dQw4w9WgXcQ", "Şarkı ♪ 日本語", "Kanal", "UC123", 1.0, False)
    transcript = Transcript(
        video=video,
        language_code="tr",
        language="Turkish",
        is_generated=False,
        segments=(Segment(0, 1, "a"),),
    )
    assert '"title": "Şarkı ♪ 日本語"' in to_json(transcript)


def test_text_joins_segments() -> None:
    segments = (Segment(0, 1, "  hello\nworld "), Segment(1, 1, ""), Segment(2, 1, "again"))
    assert to_text(segments) == "hello world again\n"
    assert to_text(segments, separator="\n") == "hello world\nagain\n"
    assert to_text(()) == ""


def test_pretty_uses_minutes_and_indents_extra_lines() -> None:
    assert to_pretty((Segment(5.2, 1, "first"), Segment(65.9, 1, "second\nline two"))) == (
        "[00:05] first\n[01:05] second\n        line two\n"
    )


def test_pretty_switches_to_hours_past_one_hour() -> None:
    assert to_pretty((Segment(5, 1, "a"), Segment(3725, 1, "b"))) == "[00:00:05] a\n[01:02:05] b\n"
    assert to_pretty(()) == ""


@pytest.mark.parametrize(
    ("name", "expected"),
    [("a.srt", "srt"), ("a.VTT", "vtt"), ("dir/a.json", "json"), ("a.txt", "txt")],
)
def test_format_from_extension(name: str, expected: str) -> None:
    assert format_for_path(name) == expected


def test_explicit_format_wins() -> None:
    assert format_for_path("a.txt", "pretty") == "pretty"


@pytest.mark.parametrize(
    ("path", "explicit"), [("a.docx", None), ("noext", None), ("a.srt", "doc")]
)
def test_unknown_formats_raise(path: str, explicit: str | None) -> None:
    with pytest.raises(UnsupportedFormat):
        format_for_path(path, explicit)


def test_render_dispatches_every_format() -> None:
    transcript = make_transcript(*SEGMENTS)
    assert render(transcript, "srt") == to_srt(SEGMENTS)
    assert render(transcript, "vtt") == to_vtt(SEGMENTS)
    assert render(transcript, "json") == to_json(transcript)
    assert render(transcript, "txt") == to_text(SEGMENTS)
    assert render(transcript, "pretty") == to_pretty(SEGMENTS)
    assert set(FORMATS) == {"srt", "vtt", "json", "txt", "pretty"}
    assert EXTENSIONS[".srt"] == "srt"
