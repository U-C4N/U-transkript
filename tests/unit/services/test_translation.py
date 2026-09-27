"""Tests for the translation engine, driven by a deterministic fake translator."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.fake_translator import FakeTranslator, echo
from tests.helpers.json_schema import schema_errors
from utmax.core.bilingual import bilingual
from utmax.core.translate.batching import InvalidResponse
from utmax.core.translate.protocol import request_schema, response_schema, system_prompt
from utmax.errors import (
    InvalidOption,
    ProviderRateLimited,
    TranslationError,
    TranslationMismatch,
    TranslationRefused,
)
from utmax.models import Segment, Transcript, Word
from utmax.services.translation import translate_transcript

MANUAL = make_transcript(
    Segment(1.0, 2.0, "Hello there."),
    Segment(3.0, 1.5, "  How are\n  you?  "),
    Segment(5.0, 1.0, "   "),
    Segment(6.0, 1.0, "Bye."),
)


def numbered(count: int) -> Transcript:
    return make_transcript(*(Segment(float(i), 1.0, f"Line {i}.") for i in range(count)))


def test_translations_keep_the_timings_and_remember_their_source() -> None:
    result = translate_transcript(MANUAL, "tr", FakeTranslator())
    assert [segment.text for segment in result] == ["HELLO THERE.", "HOW ARE\nYOU?", "BYE."]
    assert [(segment.start, segment.duration) for segment in result] == [
        (1.0, 2.0),
        (3.0, 1.5),
        (6.0, 1.0),
    ]
    assert (result.language_code, result.language, result.is_generated) == ("tr", "Turkish", True)
    assert (result.translated_from, result.translator) == ("en", "fake=echo-1")
    assert result.video == MANUAL.video
    assert result.source is not None
    assert [segment.text for segment in result.source] == [
        "Hello there.",
        "  How are\n  you?  ",
        "Bye.",
    ]


def test_every_request_follows_the_protocol() -> None:
    translator = FakeTranslator()
    translate_transcript(MANUAL, "pt-BR", translator, instructions="  Use informal speech. ")
    (request,) = translator.requests
    assert schema_errors(request, request_schema()) == []
    assert request["source_language"] == {"code": "en", "name": "English"}
    assert request["target_language"] == {"code": "pt-BR", "name": "Portuguese"}
    assert request["instructions"] == "Use informal speech."
    assert request["items"] == [
        {"id": 0, "text": "Hello there."},
        {"id": 1, "text": "How are\nyou?"},
        {"id": 2, "text": "Bye."},
    ]
    assert translator.systems == [system_prompt()]
    assert translator.schemas == [response_schema()]


def test_unknown_target_codes_are_their_own_name() -> None:
    assert translate_transcript(MANUAL, "zz", FakeTranslator()).language == "zz"


def test_batches_follow_the_translator_options_and_carry_context() -> None:
    translator = FakeTranslator(batch_items=3, context_items=2, concurrency=1)
    translate_transcript(numbered(7), "de", translator)
    assert translator.batches == [[0, 1, 2], [3, 4, 5], [6]]
    assert translator.requests[1]["context_before"] == ["Line 1.", "Line 2."]
    assert translator.requests[1]["context_after"] == ["Line 6."]


def test_auto_tracks_are_merged_into_sentences_unless_told_otherwise() -> None:
    auto = make_transcript(
        Segment(0.0, 1.0, "hello", (Word("hello", 0.0),)),
        Segment(1.0, 1.0, "world.", (Word("world.", 1.0),)),
        Segment(2.0, 1.0, "again", (Word("again", 2.0),)),
        is_generated=True,
    )
    merged = translate_transcript(auto, "de", FakeTranslator())
    assert [segment.text for segment in merged] == ["HELLO WORLD.", "AGAIN"]
    assert merged.source is not None
    assert [segment.text for segment in merged.source] == ["hello world.", "again"]
    assert len(translate_transcript(auto, "de", FakeTranslator(), resegment=False)) == 3
    manual = make_transcript(Segment(0.0, 1.0, "one"), Segment(1.0, 1.0, "two."))
    assert len(translate_transcript(manual, "de", FakeTranslator(), resegment=True)) == 1


def test_an_unusable_answer_is_retried() -> None:
    answers = iter(['{"items": []}'])

    def script(request: dict[str, Any]) -> str:
        return next(answers, "") or echo(request)

    translator = FakeTranslator(script)
    assert translate_transcript(MANUAL, "tr", translator)[0].text == "HELLO THERE."
    assert translator.batches == [[0, 1, 2], [0, 1, 2]]


def test_a_truncated_answer_is_retried() -> None:
    failures = iter([InvalidResponse("the answer was cut off", raw='{"items": [')])

    def script(request: dict[str, Any]) -> str:
        failure = next(failures, None)
        if failure is not None:
            raise failure
        return echo(request)

    translator = FakeTranslator(script)
    assert len(translate_transcript(MANUAL, "tr", translator)) == 3
    assert len(translator.requests) == 2


def test_a_batch_that_keeps_failing_is_split_in_half() -> None:
    def script(request: dict[str, Any]) -> str:
        return "not json" if len(request["items"]) > 2 else echo(request)

    translator = FakeTranslator(script, concurrency=1)
    result = translate_transcript(numbered(5), "tr", translator)
    assert [segment.text for segment in result] == [f"LINE {i}." for i in range(5)]
    assert translator.batches == [
        [0, 1, 2, 3, 4],
        [0, 1, 2, 3, 4],
        [0, 1],
        [2, 3, 4],
        [2, 3, 4],
        [2],
        [3, 4],
    ]
    assert translator.requests[5]["context_before"] == ["Line 0.", "Line 1."]
    assert translator.requests[5]["context_after"] == ["Line 3.", "Line 4."]


def test_a_cue_that_never_translates_raises_translation_mismatch() -> None:
    def script(request: dict[str, Any]) -> str:
        kept = [item for item in request["items"] if item["id"] != 1]
        return json.dumps({"items": kept})

    translator = FakeTranslator(script, concurrency=1)
    with pytest.raises(TranslationMismatch, match="cue 1") as caught:
        translate_transcript(MANUAL, "tr", translator)
    error = caught.value
    assert error.ids == (1,)
    assert error.provider == "fake"
    assert error.video_id == MANUAL.video.video_id
    assert error.raw_excerpt == '{"items": []}'
    assert translator.batches == [[0, 1, 2], [0, 1, 2], [0], [1, 2], [1, 2], [1], [1]]


def test_the_raw_excerpt_is_short() -> None:
    translator = FakeTranslator(lambda request: "x" * 1000)
    with pytest.raises(TranslationMismatch) as caught:
        translate_transcript(make_transcript(Segment(0.0, 1.0, "Hi.")), "tr", translator)
    assert caught.value.raw_excerpt == "x" * 300


@pytest.mark.parametrize(
    "error",
    [
        ProviderRateLimited("slow down", provider="fake"),
        TranslationRefused("no", provider="fake"),
    ],
)
def test_provider_errors_are_raised_at_once(error: TranslationError) -> None:
    def script(request: dict[str, Any]) -> str:
        raise error

    translator = FakeTranslator(script)
    with pytest.raises(type(error)) as caught:
        translate_transcript(MANUAL, "tr", translator)
    assert len(translator.requests) == 1
    assert caught.value.video_id == MANUAL.video.video_id


def test_a_failure_cancels_the_batches_that_have_not_started() -> None:
    def script(request: dict[str, Any]) -> str:
        raise ProviderRateLimited("slow down", provider="fake")

    translator = FakeTranslator(script, batch_items=1, concurrency=1)
    with pytest.raises(ProviderRateLimited):
        translate_transcript(numbered(3), "tr", translator)
    assert translator.batches == [[0]]


def test_results_keep_their_order_while_batches_run_in_parallel() -> None:
    barrier = threading.Barrier(4, timeout=5)

    def script(request: dict[str, Any]) -> str:
        barrier.wait()
        time.sleep(0.01 * (4 - request["items"][0]["id"] % 4))
        return echo(request)

    translator = FakeTranslator(script, batch_items=1, concurrency=4)
    result = translate_transcript(numbered(8), "tr", translator)
    assert [segment.text for segment in result] == [f"LINE {i}." for i in range(8)]
    assert sorted(batch[0] for batch in translator.batches) == list(range(8))


def test_empty_and_blank_transcripts_make_no_requests() -> None:
    translator = FakeTranslator()
    blank = make_transcript(Segment(0.0, 1.0, "  "), Segment(1.0, 1.0, "\n"))
    for transcript in (make_transcript(), blank):
        result = translate_transcript(transcript, "tr", translator)
        assert (len(result), result.language_code, result.translator) == (0, "tr", "fake=echo-1")
        assert result.source is not None
        assert len(result.source) == 0
    assert translator.requests == []


@pytest.mark.parametrize("to", ["", "   ", "Turkish", "tr/../x", "t", "tr_TR", "en-", None])
def test_invalid_target_languages_are_rejected_before_any_request(to: str) -> None:
    translator = FakeTranslator()
    with pytest.raises(InvalidOption, match="not a language code"):
        translate_transcript(MANUAL, to, translator)
    assert translator.requests == []


@pytest.mark.parametrize(
    ("to", "code"), [(" tr ", "tr"), ("zh-Hant", "zh-Hant"), ("es-419", "es-419")]
)
def test_language_tags_are_accepted_and_trimmed(to: str, code: str) -> None:
    assert translate_transcript(MANUAL, to, FakeTranslator()).language_code == code


def test_bilingual_transcripts_are_not_translated() -> None:
    combined = bilingual(MANUAL, translate_transcript(MANUAL, "tr", FakeTranslator()))
    translator = FakeTranslator()
    with pytest.raises(InvalidOption, match="bilingual"):
        translate_transcript(combined, "de", translator)
    assert translator.requests == []
