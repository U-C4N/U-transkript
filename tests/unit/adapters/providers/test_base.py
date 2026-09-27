"""Tests for the Translator base class."""

from __future__ import annotations

import pytest

from tests.helpers.fake_translator import FakeTranslator
from utmax.adapters.providers.base import Translator, positive_int
from utmax.core.translate.protocol import translation_rules
from utmax.errors import InvalidOption


def test_engine_defaults_match_the_protocol_file() -> None:
    translator = FakeTranslator()
    rules = translation_rules()
    assert translator.batch_chars == rules.batch_chars
    assert translator.batch_items == rules.batch_items
    assert translator.context_items == rules.context_items
    assert translator.concurrency == rules.concurrency
    assert translator.max_attempts == rules.max_attempts


def test_engine_options_can_be_tuned() -> None:
    translator = FakeTranslator(batch_chars=100, batch_items=5, context_items=0, concurrency=1)
    assert (translator.batch_chars, translator.batch_items, translator.context_items) == (100, 5, 0)
    assert (translator.concurrency, translator.max_attempts) == (1, 2)


@pytest.mark.parametrize(
    "options",
    [
        {"batch_chars": 0},
        {"batch_items": -1},
        {"context_items": -1},
        {"concurrency": 0},
        {"max_attempts": 0},
        {"batch_items": True},
        {"batch_chars": 2.5},
    ],
)
def test_bad_engine_options_are_rejected(options: dict[str, object]) -> None:
    with pytest.raises(InvalidOption, match="must be an integer"):
        FakeTranslator(**options)  # type: ignore[arg-type]


def test_positive_int_returns_valid_values() -> None:
    assert positive_int("max_tokens", 16000) == 16000
    assert positive_int("context_items", 0, minimum=0) == 0


def test_provider_comes_from_the_name_and_repr_shows_only_the_name() -> None:
    translator = FakeTranslator(name="local=my-model")
    assert translator.provider == "local"
    assert repr(translator) == "FakeTranslator('local=my-model')"


def test_the_base_class_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        Translator()  # type: ignore[abstract]
