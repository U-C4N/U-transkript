"""Tests for bilingual transcripts and for how every format renders them."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.helpers.builders import VIDEO, make_transcript
from utmax.core.bilingual import bilingual
from utmax.core.formats import render, to_bilingual_text, to_srt, to_text
from utmax.errors import InvalidOption
from utmax.models import Segment, Transcript

ENGLISH = make_transcript(
    Segment(1.0, 2.0, "We're no strangers to love"),
    Segment(3.0, 2.0, "You know the rules\nand so do I"),
)
LINE_1 = "A\U0000015fka yabanc\U00000131 de\U0000011filiz"
LINE_2 = "Kurallar\U00000131 biliyorsun\nben de"


def ai_translation(source: Transcript, *texts: str) -> Transcript:
    """What utmax.translate returns: source timings, target texts and the exact source cues."""
    return Transcript(
        video=source.video,
        language_code="tr",
        language="Turkish",
        is_generated=True,
        segments=tuple(
            Segment(cue.start, cue.duration, text)
            for cue, text in zip(source.segments, texts, strict=True)
        ),
        translated_from=source.language_code,
        translator="claude=claude-opus-5",
        source=source,
    )


TURKISH = ai_translation(ENGLISH, LINE_1, LINE_2)


def test_ai_translations_pair_one_to_one_with_their_source_cues() -> None:
    result = bilingual(ENGLISH, TURKISH)
    assert [segment.text for segment in result] == [
        f"We're no strangers to love\n{LINE_1}",
        f"You know the rules\nand so do I\n{LINE_2}",
    ]
    assert [(segment.start, segment.duration) for segment in result] == [(1.0, 2.0), (3.0, 2.0)]
    assert (result.language_code, result.language) == ("en+tr", "English + Turkish")
    assert result.is_bilingual
    assert result.is_generated
    assert (result.translated_from, result.translator) == ("en", "claude=claude-opus-5")
    assert result.video == VIDEO
    assert result.source is None


def test_translation_first_swaps_the_lines_but_not_the_code() -> None:
    result = bilingual(ENGLISH, TURKISH, translation_first=True)
    assert result[0].text == f"{LINE_1}\nWe're no strangers to love"
    assert result.language_code == "en+tr"


def test_resegmented_source_cues_win_over_the_raw_auto_track() -> None:
    raw = make_transcript(
        Segment(0.0, 1.0, "hello"), Segment(1.0, 1.0, "world."), is_generated=True
    )
    merged = make_transcript(Segment(0.0, 2.0, "hello world."), is_generated=True)
    result = bilingual(raw, ai_translation(merged, "merhaba d\U000000fcnya."))
    assert [segment.text for segment in result] == ["hello world.\nmerhaba d\U000000fcnya."]


def test_other_translations_follow_the_original_timing() -> None:
    original = make_transcript(
        Segment(0.5, 1.5, "A"), Segment(2.0, 2.0, "B"), Segment(5.0, 2.0, "C")
    )
    german = make_transcript(
        Segment(0.0, 0.4, "a0"),
        Segment(0.2, 0.8, "a1"),
        Segment(1.0, 0.9, "a2"),
        Segment(2.5, 1.0, "b"),
        Segment(4.1, 0.5, "gap"),
        Segment(8.0, 1.0, "late"),
        Segment(9.5, 1.0, "   "),
        language_code="de",
        language="German",
    )
    result = bilingual(original, german)
    assert [segment.text for segment in result] == ["A\na0 a1 a2", "B\nb gap", "C\nlate"]
    assert [segment.start for segment in result] == [0.5, 2.0, 5.0]
    assert result.language == "English + German"
    assert (result.translated_from, result.translator) == (None, None)
    assert not result.is_generated


def test_a_translation_of_another_track_is_aligned_by_time_not_zipped() -> None:
    german = make_transcript(
        Segment(1.0, 2.0, "Wir sind keine Fremden"),
        Segment(3.0, 2.0, "Du kennst die Regeln"),
        language_code="de-DE",
        language="German (Germany)",
    )
    result = bilingual(german, TURKISH)
    assert [segment.text for segment in result] == [
        f"Wir sind keine Fremden\n{LINE_1}",
        f"Du kennst die Regeln\n{LINE_2}",
    ]
    assert (result.language_code, result.language) == ("de-DE+tr", "German + Turkish")


def test_a_source_of_another_length_is_ignored() -> None:
    broken = replace(TURKISH, source=make_transcript(Segment(1.0, 2.0, "SOURCE")))
    result = bilingual(ENGLISH, broken)
    assert [segment.text for segment in result] == [
        f"We're no strangers to love\n{LINE_1}",
        f"You know the rules\nand so do I\n{LINE_2}",
    ]


def test_original_cues_without_a_translation_keep_their_text_alone() -> None:
    original = make_transcript(
        Segment(0.0, 1.0, "one"), Segment(1.0, 1.0, "   "), Segment(10.0, 1.0, "two")
    )
    translation = make_transcript(Segment(0.0, 1.0, "bir"), language_code="tr", language="Turkish")
    assert [segment.text for segment in bilingual(original, translation)] == ["one\nbir", "two"]


def test_unknown_language_codes_fall_back_to_the_transcript_names() -> None:
    private = make_transcript(Segment(0.0, 1.0, "nuqneH"), language_code="zz", language="Klingon")
    result = bilingual(private, make_transcript(Segment(0.0, 1.0, "hello")))
    assert (result.language_code, result.language) == ("zz+en", "Klingon + English")


def test_bilingual_transcripts_cannot_be_combined_again() -> None:
    combined = bilingual(ENGLISH, TURKISH)
    with pytest.raises(InvalidOption, match="already bilingual"):
        bilingual(combined, TURKISH)
    with pytest.raises(InvalidOption, match="already bilingual"):
        bilingual(ENGLISH, combined)


def test_empty_transcripts_give_an_empty_bilingual_transcript() -> None:
    result = bilingual(make_transcript(), make_transcript(language_code="tr", language="Turkish"))
    assert (len(result), result.language_code) == (0, "en+tr")


def test_srt_and_vtt_show_both_lines_of_every_cue() -> None:
    result = bilingual(ENGLISH, TURKISH)
    srt = render(result, "srt")
    assert srt == to_srt(result.segments)
    assert f"00:00:01,000 --> 00:00:03,000\nWe're no strangers to love\n{LINE_1}\n" in srt
    assert f"00:00:01.000 --> 00:00:03.000\nWe're no strangers to love\n{LINE_1}\n" in render(
        result, "vtt"
    )


def test_txt_keeps_line_breaks_and_separates_cues_with_a_blank_line() -> None:
    assert render(bilingual(ENGLISH, TURKISH), "txt") == (
        f"We're no strangers to love\n{LINE_1}\n\nYou know the rules\nand so do I\n{LINE_2}\n"
    )
    assert to_bilingual_text(()) == ""
    assert render(ENGLISH, "txt") == to_text(ENGLISH.segments)


def test_pretty_indents_the_translation_lines() -> None:
    assert render(bilingual(ENGLISH, TURKISH), "pretty").startswith(
        f"[00:01] We're no strangers to love\n        {LINE_1}\n[00:03] You know the rules\n"
    )


def test_json_keeps_both_lines_in_one_text() -> None:
    data = json.loads(render(bilingual(ENGLISH, TURKISH), "json"))
    assert (data["language_code"], data["language"]) == ("en+tr", "English + Turkish")
    assert data["segments"][0]["text"] == f"We're no strangers to love\n{LINE_1}"


def test_saving_a_bilingual_transcript_uses_the_bilingual_layout(tmp_path: Path) -> None:
    result = bilingual(ENGLISH, TURKISH)
    data = result.save(tmp_path / "rick.en+tr.txt").read_bytes()
    assert data.decode("utf-8") == render(result, "txt")
    assert b"\r\n" not in data
