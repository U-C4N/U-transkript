"""Tests for translation batches, requests and answer validation."""

from __future__ import annotations

import json

import pytest

from tests.helpers.json_schema import schema_errors
from utmax.core.translate.batching import (
    Batch,
    InvalidResponse,
    Item,
    build_request,
    make_batch,
    parse_response,
    plan_batches,
    split_batch,
)
from utmax.core.translate.protocol import request_schema
from utmax.models import Language

TEXTS = [f"line {index}" for index in range(10)]


def test_make_batch_adds_source_context_on_both_sides() -> None:
    batch = make_batch(TEXTS, 4, 6, context_items=3)
    assert batch.items == (Item(4, "line 4"), Item(5, "line 5"))
    assert batch.ids == (4, 5)
    assert batch.context_before == ("line 1", "line 2", "line 3")
    assert batch.context_after == ("line 6", "line 7", "line 8")


def test_context_is_clipped_at_the_edges_and_can_be_disabled() -> None:
    assert make_batch(TEXTS, 0, 2, context_items=3).context_before == ()
    assert make_batch(TEXTS, 8, 10, context_items=3).context_after == ()
    assert make_batch(TEXTS, 4, 6, context_items=0) == Batch((Item(4, "line 4"), Item(5, "line 5")))


def test_batches_respect_the_item_limit() -> None:
    batches = plan_batches(TEXTS, max_chars=4000, max_items=4, context_items=3)
    assert [batch.ids for batch in batches] == [(0, 1, 2, 3), (4, 5, 6, 7), (8, 9)]
    assert batches[1].context_before == ("line 1", "line 2", "line 3")
    assert batches[1].context_after == ("line 8", "line 9")


def test_batches_respect_the_character_limit() -> None:
    texts = ["a" * 30, "b" * 30, "c" * 30, "d" * 10]
    batches = plan_batches(texts, max_chars=60, max_items=50, context_items=0)
    assert [batch.ids for batch in batches] == [(0, 1), (2, 3)]


def test_an_oversized_cue_gets_a_batch_of_its_own() -> None:
    texts = ["short", "x" * 500, "tail"]
    batches = plan_batches(texts, max_chars=100, max_items=50, context_items=1)
    assert [batch.ids for batch in batches] == [(0,), (1,), (2,)]


def test_no_texts_means_no_batches() -> None:
    assert plan_batches([], max_chars=4000, max_items=50, context_items=3) == []


def test_split_halves_a_batch_and_recomputes_the_context() -> None:
    batch = make_batch(TEXTS, 2, 7, context_items=2)
    first, second = split_batch(batch, TEXTS, context_items=2)
    assert (first.ids, second.ids) == ((2, 3), (4, 5, 6))
    assert first.context_before == ("line 0", "line 1")
    assert first.context_after == ("line 4", "line 5")
    assert second.context_before == ("line 2", "line 3")
    assert second.context_after == ("line 7", "line 8")


def test_a_single_item_cannot_be_split() -> None:
    with pytest.raises(ValueError, match="two or more"):
        split_batch(make_batch(TEXTS, 3, 4, context_items=0), TEXTS, context_items=0)


def test_requests_match_the_protocol_schema_and_keep_text_literal() -> None:
    texts = ["\U0000266a We're no strangers \U0000266a", "A\U0000015fk\nsat\U00000131r"]
    batch = make_batch(texts, 1, 2, context_items=3)
    raw = build_request(
        batch,
        source=Language("en", "English"),
        target=Language("tr", "Turkish"),
        instructions="Use informal Turkish.",
    )
    assert "\U0000266a" in raw
    assert "\\u" not in raw
    document = json.loads(raw)
    assert schema_errors(document, request_schema()) == []
    assert document == {
        "source_language": {"code": "en", "name": "English"},
        "target_language": {"code": "tr", "name": "Turkish"},
        "instructions": "Use informal Turkish.",
        "context_before": ["\U0000266a We're no strangers \U0000266a"],
        "items": [{"id": 1, "text": "A\U0000015fk\nsat\U00000131r"}],
        "context_after": [],
    }


def test_requests_without_instructions_send_null() -> None:
    raw = build_request(
        make_batch(["hi"], 0, 1, context_items=0),
        source=Language("en", "English"),
        target=Language("de", "German"),
    )
    assert json.loads(raw)["instructions"] is None


def test_a_valid_answer_is_parsed_and_stripped() -> None:
    raw = '{"items": [{"id": 3, "text": "  Merhaba\\nd\\u00fcnya "}, {"id": 4, "text": "Selam"}]}'
    assert parse_response(raw, [3, 4]) == {3: "Merhaba\nd\U000000fcnya", 4: "Selam"}


@pytest.mark.parametrize(
    "raw",
    [
        '```json\n{"items": [{"id": 0, "text": "Hallo"}]}\n```',
        'Here is the translation:\n{"items": [{"id": 0, "text": "Hallo"}]}',
        '  {"items": [{"id": 0, "text": "Hallo"}]}  \n',
    ],
)
def test_decorated_json_is_accepted(raw: str) -> None:
    assert parse_response(raw, [0]) == {0: "Hallo"}


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("Sorry, I cannot help with that.", "not valid JSON"),
        ('{"items": [{"id": 0, "text": "cut', "not valid JSON"),
        ("[1, 2]", 'no "items" list'),
        ('{"translations": []}', 'no "items" list'),
        ('{"items": ["Hallo"]}', "not a JSON object"),
        ('{"items": [{"id": "0", "text": "Hallo"}]}', "is not an integer"),
        ('{"items": [{"id": true, "text": "Hallo"}]}', "is not an integer"),
        ('{"items": [{"id": 0, "text": "   "}]}', "empty text"),
        ('{"items": [{"id": 0, "text": null}]}', "empty text"),
        ('{"items": [{"id": 0, "text": "a"}, {"id": 0, "text": "b"}]}', "appears twice"),
        ('{"items": []}', r"missing \[0\]"),
        ('{"items": [{"id": 0, "text": "a"}, {"id": 1, "text": "b"}]}', r"unexpected \[1\]"),
    ],
)
def test_unusable_answers_raise_invalid_response(raw: str, reason: str) -> None:
    with pytest.raises(InvalidResponse, match=reason) as caught:
        parse_response(raw, [0])
    assert caught.value.raw == raw
    assert caught.value.reason in str(caught.value)
