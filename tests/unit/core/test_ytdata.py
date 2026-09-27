"""Tests for the defensive JSON readers."""

from __future__ import annotations

from utmax.core.ytdata import items, mapping, text_of, texts_of


def test_mapping_and_items_ignore_wrong_types() -> None:
    assert mapping({"a": 1}) == {"a": 1}
    assert mapping([1]) == {}
    assert items([1, 2]) == [1, 2]
    assert items({"a": 1}) == []


def test_text_objects() -> None:
    assert text_of({"simpleText": "Hello"}) == "Hello"
    assert text_of({"runs": [{"text": "Hel"}, {"text": "lo"}, {"bold": True}]}) == "Hello"
    assert text_of(None) == ""
    assert texts_of({"runs": [{"text": "a"}, {"text": ""}, "junk", {"text": "b"}]}) == ("a", "b")
