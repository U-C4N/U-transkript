"""Tests for reading SRT and WebVTT text back into segments (e.g. an assistant's translation)."""

from __future__ import annotations

import pytest

from tests.helpers.builders import VIDEO
from utmax.core.formats import parse_subtitles, to_srt, to_vtt
from utmax.errors import InvalidOption
from utmax.models import Segment, Transcript

SEGMENTS = (
    Segment(1.36, 1.68, "[♪♪♪]"),
    Segment(18.64, 3.24, "♪ We're no strangers to love ♪"),
    Segment(22.64, 4.4, "♪ You know the rules\nand so do I ♪"),
    Segment(3725.5, 2.0, "an hour in"),
)


def test_srt_reads_back_what_utmax_writes() -> None:
    assert parse_subtitles(to_srt(SEGMENTS)) == SEGMENTS


def test_vtt_reads_back_what_utmax_writes_escapes_and_styling_included() -> None:
    styled = (*SEGMENTS, Segment(4000.0, 1.5, "Fish & <i>chips</i> > 3"))
    assert parse_subtitles(to_vtt(styled)) == styled


def test_srt_from_elsewhere_is_read_leniently() -> None:
    text = (
        "\U0000feff1\r\n00:00:01,000 --> 00:00:02,500\r\nMerhaba\r\n\r\n"
        "00:00:03,000 --> 00:00:04,000\r\n  iki satir  \r\nalt satir\r\n"
        "3\r\n00:00:05,000 --> 00:00:06,00\r\nnumarasiz bosluk yok\r\n"
    )
    assert parse_subtitles(text) == (
        Segment(1.0, 1.5, "Merhaba"),
        Segment(3.0, 1.0, "iki satir\nalt satir"),
        Segment(5.0, 1.0, "numarasiz bosluk yok"),
    )


def test_vtt_headers_notes_settings_and_cue_tags_are_skipped() -> None:
    text = (
        "WEBVTT - Turkish\nKind: captions\n\nNOTE written by hand\nover two lines\n\n"
        "STYLE\n::cue { color: lime }\n\n"
        "intro\n00:01.000 --> 00:02.000 align:start position:10%\n"
        "<v Rick>Merhaba <c.yellow>dunya</c><00:00:01.500> &amp; <b>herkes</b>\n"
    )
    assert parse_subtitles(text) == (Segment(1.0, 1.0, "Merhaba dunya & <b>herkes</b>"),)


def test_a_cue_that_ends_before_it_starts_lasts_no_time() -> None:
    (segment,) = parse_subtitles("00:00:05,000 --> 00:00:04,000\nback in time\n")
    assert (segment.start, segment.duration) == (5.0, 0.0)


@pytest.mark.parametrize("text", ["", "WEBVTT\n\n", "just some words\nno times\n"])
def test_text_without_cues_is_refused(text: str) -> None:
    with pytest.raises(InvalidOption, match="no subtitle cue"):
        parse_subtitles(text)


def test_transcript_from_srt_describes_the_translation() -> None:
    turkish = Transcript.from_srt(
        "1\n00:00:01,000 --> 00:00:02,000\nMerhaba\n",
        "tr",
        video=VIDEO,
        translated_from="en",
        translator="assistant",
    )
    assert turkish.segments == (Segment(1.0, 1.0, "Merhaba"),)
    assert (turkish.video, turkish.language_code, turkish.language) == (VIDEO, "tr", "Turkish")
    assert (turkish.translated_from, turkish.translator, turkish.is_generated) == (
        "en",
        "assistant",
        True,
    )
    unknown = Transcript.from_srt("00:00:01,000 --> 00:00:02,000\nx\n", "xx-YY", video=VIDEO)
    assert (unknown.language, unknown.is_generated, unknown.translator) == ("xx-YY", False, None)
    named = Transcript.from_srt(
        "00:00:01,000 --> 00:00:02,000\nx\n", "tr", video=VIDEO, language="Turkce"
    )
    assert named.language == "Turkce"


def test_code_fences_and_a_leading_blank_line_are_ignored() -> None:
    text = "\n```vtt\nWEBVTT\n\n00:01.000 --> 00:02.000\n<v Rick>Fish &amp; chips\n```\n"
    assert parse_subtitles(text) == (Segment(1.0, 1.0, "Fish & chips"),)


def test_subtitles_without_any_text_are_refused() -> None:
    with pytest.raises(InvalidOption, match="no text"):
        parse_subtitles("1\n00:00:01,000 --> 00:00:02,000\n\nMerhaba\n")
