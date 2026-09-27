"""Tests for merge_sentences."""

from __future__ import annotations

import itertools

import pytest

from tests.helpers.builders import make_transcript
from utmax.core.segmentation import merge_sentences
from utmax.core.translate.protocol import SegmentationRules, segmentation_rules
from utmax.models import Segment, Word


def asr(end: float, *words: tuple[str, float]) -> Segment:
    """An auto-generated segment whose words start at the given times and which ends at ``end``."""
    start = words[0][1]
    return Segment(
        start=start,
        duration=end - start,
        text=" ".join(text for text, _ in words),
        words=tuple(Word(text, at) for text, at in words),
    )


def texts(segments: tuple[Segment, ...]) -> list[str]:
    return [segment.text for segment in segments]


def test_protocol_file_provides_the_default_rules() -> None:
    rules = segmentation_rules()
    assert rules.terminal_punctuation == ".!?…。！？"
    assert (rules.max_gap_seconds, rules.max_duration_seconds, rules.max_characters) == (
        1.0,
        7.0,
        100,
    )
    assert '"' in rules.closing_characters
    assert "'" in rules.closing_characters


def test_sentence_punctuation_closes_cues_using_word_timings() -> None:
    merged = merge_sentences(
        (
            asr(1.2, ("Hello", 0.0), ("world.", 0.4), ("How", 0.8)),
            asr(2.0, ("are", 1.2), ("you?", 1.5)),
        )
    )
    assert texts(merged) == ["Hello world.", "How are you?"]
    assert (merged[0].start, merged[0].end) == pytest.approx((0.0, 0.8))
    assert (merged[1].start, merged[1].end) == pytest.approx((0.8, 2.0))
    assert [word.text for word in merged[1].words] == ["How", "are", "you?"]


def test_a_long_pause_closes_a_cue() -> None:
    merged = merge_sentences((asr(0.5, ("one", 0.0)), asr(2.5, ("two", 2.0))))
    assert texts(merged) == ["one", "two"]


def test_cues_stop_growing_at_seven_seconds() -> None:
    words = tuple((f"w{i}", float(i)) for i in range(10))
    merged = merge_sentences((asr(10.0, *words),))
    assert texts(merged) == ["w0 w1 w2 w3 w4 w5 w6", "w7 w8 w9"]
    assert (merged[0].start, merged[0].end) == pytest.approx((0.0, 7.0))


def test_cues_stop_growing_at_one_hundred_characters() -> None:
    words = tuple(("abcd", i * 0.1) for i in range(30))
    merged = merge_sentences((asr(3.0, *words),))
    assert len(merged[0].text) == 104
    assert len(merged[0].words) == 21


def test_bracketed_sound_tags_stand_alone() -> None:
    merged = merge_sentences(
        (
            Segment(0.0, 2.0, "[Music]"),
            asr(3.0, ("we're", 2.0), ("no", 2.3)),
            Segment(3.5, 1.0, "[Applause]"),
        )
    )
    assert texts(merged) == ["[Music]", "we're no", "[Applause]"]


def test_rolling_captions_never_overlap_after_merging() -> None:
    merged = merge_sentences((asr(6.0, ("a", 0.0), ("b.", 0.5)), asr(5.0, ("c", 1.0), ("d", 1.5))))
    assert len(merged) == 2
    starts = [segment.start for segment in merged]
    assert starts == sorted(starts)
    for current, following in itertools.pairwise(merged):
        assert current.end <= following.start


def test_segments_without_words_are_merged_until_punctuation() -> None:
    merged = merge_sentences(
        (Segment(0, 1, "Hello"), Segment(1, 1, "world."), Segment(2, 1, "Bye"))
    )
    assert texts(merged) == ["Hello world.", "Bye"]
    assert (merged[0].start, merged[0].end) == (0, 2)


def test_closing_quotes_and_cjk_punctuation_end_sentences() -> None:
    merged = merge_sentences(
        (
            Segment(0, 1, 'He said "stop."'),
            Segment(1, 1, "すごい。"),
            Segment(2, 1, "done"),
        )
    )
    assert texts(merged) == ['He said "stop."', "すごい。", "done"]


def test_apostrophe_closed_quotes_end_sentences() -> None:
    merged = merge_sentences((Segment(0, 1, "He said 'stop.'"), Segment(1, 1, "Bye")))
    assert texts(merged) == ["He said 'stop.'", "Bye"]


def test_empty_input_and_blank_segments() -> None:
    assert merge_sentences(()) == ()
    assert merge_sentences((Segment(0, 1, "  "),)) == ()


def test_custom_rules_override_the_defaults() -> None:
    rules = SegmentationRules(".", "", 1.0, 7.0, 5)
    merged = merge_sentences(
        (Segment(0, 1, "abc"), Segment(1, 1, "def"), Segment(2, 1, "g")), rules
    )
    assert texts(merged) == ["abc def", "g"]


def test_transcript_merge_sentences_keeps_metadata() -> None:
    transcript = make_transcript(
        Segment(0, 1, "Hello"), Segment(1, 1, "world."), language_code="en", is_generated=True
    )
    merged = transcript.merge_sentences()
    assert merged.text == "Hello world."
    assert len(merged) == 1
    assert (merged.video, merged.language_code, merged.is_generated) == (
        transcript.video,
        "en",
        True,
    )
