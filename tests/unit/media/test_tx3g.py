"""Tests for tx3g subtitle tracks."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from tests.helpers.builders import make_transcript
from utmax.core.formats import to_srt
from utmax.core.media.tx3g import (
    Cue,
    decode_sample,
    default_subtitle_index,
    encode_sample,
    normalize_cues,
    sample_entry,
    subtitle_track,
    track_languages,
    track_name,
)
from utmax.errors import InvalidOption, MuxError
from utmax.models import Segment

MESSY = (
    Segment(5.0, 1.0, "late"),
    Segment(0.0, 5.0, "  first \n  line  "),
    Segment(3.0, 2.0, "overlaps the first"),
    Segment(4.0, 0.0, "zero length"),
    Segment(6.5, 1.0, "   "),
    Segment(8.0, 2.0, "SPEAKER A: hi"),
    Segment(8.0, 1.0, "SPEAKER B: hello"),
    Segment(12.0004, 1.0006, "rounded"),
)
TURKISH = "T\xfcrk\xe7e \U0000011f\xfc\U0000015f\U00000131\xf6\xe7"
JAPANESE = "\U000065e5\U0000672c\U00008a9e"
EMOJI_AND_NOTE = "\U0001f600 \U0000266a"


def srt_cues(srt: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in srt.strip().split("\n\n"):
        lines = block.split("\n")
        start, end = (
            int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1000 + int(ms)
            for h, m, s, ms in re.findall(r"(\d+):(\d+):(\d+),(\d+)", lines[1])
        )
        cues.append(Cue(start, end, "\n".join(lines[2:])))
    return cues


def test_cues_are_timed_exactly_like_the_srt_sidecar() -> None:
    assert list(normalize_cues(MESSY)) == srt_cues(to_srt(MESSY))
    assert normalize_cues(MESSY)[0] == Cue(0, 3000, "first\nline")


@pytest.mark.parametrize("text", ["", "hello", "two\nlines", TURKISH, JAPANESE, EMOJI_AND_NOTE])
def test_samples_round_trip(text: str) -> None:
    sample = encode_sample(text)
    assert int.from_bytes(sample[:2], "big") == len(text.encode("utf-8"))
    assert decode_sample(sample) == text


def test_overlong_text_is_cut_at_a_character_boundary() -> None:
    sample = encode_sample("\U0000011f" * 40_000)  # 80 000 UTF-8 bytes
    assert int.from_bytes(sample[:2], "big") == 65_534
    assert decode_sample(sample) == "\U0000011f" * 32_767


@pytest.mark.parametrize("payload", [b"", b"\x00", b"\x00\x05abc"])
def test_short_samples_are_rejected(payload: bytes) -> None:
    with pytest.raises(MuxError, match="shorter than its length"):
        decode_sample(payload)


def test_sample_entry_is_ffmpegs_mov_text_default_with_a_sans_serif_font() -> None:
    header = bytes.fromhex("00000045") + b"tx3g" + bytes(6) + bytes.fromhex("0001")
    display = bytes.fromhex("00000000")  # display flags
    justification = bytes.fromhex("01ff")  # centred horizontally, at the bottom
    background = bytes(4)  # transparent
    text_box = bytes(8)  # top, left, bottom, right
    style = bytes.fromhex("0000000000010012ffffffff")  # chars 0-0, font 1, regular, 18 pt, white
    fonts = bytes.fromhex("00000017") + b"ftab" + bytes.fromhex("0001" + "0001" + "0a")
    expected = header + display + justification + background + text_box + style + fonts
    assert sample_entry() == expected + b"Sans-Serif"


def test_track_names() -> None:
    manual = make_transcript(language_code="en", language="English")
    assert track_name(manual) == "English"
    auto = make_transcript(language="English (auto-generated)", is_generated=True)
    assert track_name(auto) == "English (auto-generated)"
    translated = make_transcript(language_code="tr", language="Turkish")
    ai = replace(translated, translated_from="en", translator="claude=claude-opus-5")
    assert track_name(ai) == "Turkish (AI: claude=claude-opus-5)"
    assert track_name(make_transcript(language_code="tr", language="")) == "Turkish"
    assert track_name(make_transcript(language_code="xx", language=" ")) == "xx"
    both = make_transcript(language_code="en+tr", language="English + Turkish")
    assert track_name(replace(both, translator="claude=claude-opus-5")) == "English + Turkish"
    assert track_name(make_transcript(language_code="en+tr", language="")) == "English + Turkish"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("tr", ("tur", "tr")),
        ("pt-BR", ("por", "pt-BR")),
        ("zh_Hant", ("zho", "zh-Hant")),
        ("es-419", ("spa", "es-419")),
        ("en+tr", ("mul", "mul")),
        ("xx", ("und", "xx")),
        ("not a code", ("und", "und")),
    ],
)
def test_track_languages(code: str, expected: tuple[str, str]) -> None:
    assert track_languages(code) == expected


def texts(samples: tuple[tuple[int, bytes], ...]) -> list[tuple[int, str]]:
    return [(duration, decode_sample(payload)) for duration, payload in samples]


def test_gaps_become_empty_samples_from_time_zero() -> None:
    track = subtitle_track(make_transcript(Segment(1.0, 1.0, "a"), Segment(3.0, 0.5, "b")))
    assert texts(track.samples) == [(1000, ""), (1000, "a"), (1000, ""), (500, "b")]


def test_a_cue_at_zero_needs_no_leading_empty_sample() -> None:
    track = subtitle_track(make_transcript(Segment(0.0, 1.0, "a")))
    assert texts(track.samples) == [(1000, "a")]


def test_a_limit_drops_and_cuts_cues_past_the_end() -> None:
    transcript = make_transcript(
        Segment(0.0, 1.0, "a"), Segment(1.5, 2.0, "b"), Segment(4.0, 1.0, "c")
    )
    track = subtitle_track(transcript, limit=2500)
    assert texts(track.samples) == [(1000, "a"), (500, ""), (1000, "b")]


def test_a_limit_ends_the_last_cue_with_an_empty_sample() -> None:
    track = subtitle_track(make_transcript(Segment(0.5, 1.0, "a")), limit=3000)
    assert texts(track.samples) == [(500, ""), (1000, "a"), (1500, "")]


def test_transcripts_without_cues_still_make_a_track() -> None:
    assert subtitle_track(make_transcript(), limit=4000).samples == ((4000, b"\x00\x00"),)
    assert subtitle_track(make_transcript(Segment(0, 1, "  "))).samples == ((1, b"\x00\x00"),)


def test_formatting_tags_are_removed() -> None:
    text = "<i>soft</i> <b>loud</b> <u>x</u> <font>kept</font>"
    track = subtitle_track(make_transcript(Segment(0.0, 1.0, text)))
    assert decode_sample(track.samples[0][1]) == "soft loud x <font>kept</font>"


def test_subtitle_track_labels() -> None:
    transcript = make_transcript(Segment(0, 1, "merhaba"), language_code="tr", language="Turkish")
    track = subtitle_track(replace(transcript, translator="openai=gpt-5"))
    assert (track.code, track.name, track.language, track.tag) == (
        "tr",
        "Turkish (AI: openai=gpt-5)",
        "tur",
        "tr",
    )


def test_default_subtitle_index() -> None:
    assert default_subtitle_index([], None) is None
    assert default_subtitle_index(["en", "tr"], None) == 0
    assert default_subtitle_index(["en", "tr", "en+tr"], "EN+TR") == 2
    assert default_subtitle_index(["en", "tr"], " tr ") == 1


@pytest.mark.parametrize(("codes", "listed"), [(["en", "tr"], "en, tr"), ([], "none")])
def test_an_unknown_default_subtitle_is_an_invalid_option(codes: list[str], listed: str) -> None:
    with pytest.raises(InvalidOption, match=rf"no embedded subtitle track \(embedded: {listed}\)"):
        default_subtitle_index(codes, "de")
