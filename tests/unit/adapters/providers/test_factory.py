"""Tests for create_translator: provider specs to translator instances."""

from __future__ import annotations

import sys

import pytest

from tests.helpers.sdk import FakeAnthropic, FakeGenAI, FakeOpenAI
from utmax.adapters.providers import (
    TRANSLATORS,
    ClaudeTranslator,
    GeminiTranslator,
    OpenAITranslator,
    OpenRouterTranslator,
    create_translator,
)
from utmax.errors import InvalidModelSpec, InvalidOption, MissingExtra, ProviderNotInstalled


@pytest.mark.parametrize(
    ("spec", "module", "cls", "fake"),
    [
        ("claude=claude-opus-5", "anthropic", ClaudeTranslator, FakeAnthropic),
        ("openai=llama3.1:8b", "openai", OpenAITranslator, FakeOpenAI),
        ("gemini=gemini-2.5-flash", "google.genai", GeminiTranslator, FakeGenAI),
        ("openrouter=openai/gpt-5-mini", "openai", OpenRouterTranslator, FakeOpenAI),
    ],
)
def test_every_provider_gets_its_translator(spec: str, module: str, cls: type, fake: type) -> None:
    pytest.importorskip(module)
    translator = create_translator(spec, client=fake(), batch_items=10)
    assert type(translator) is cls
    assert translator.name == spec
    assert translator.batch_items == 10


def test_the_registry_covers_every_provider() -> None:
    assert set(TRANSLATORS) == {"claude", "openai", "gemini", "openrouter"}


def test_base_url_only_works_with_openai() -> None:
    with pytest.raises(InvalidOption, match="only works with the openai provider"):
        create_translator("claude=claude-opus-5", base_url="http://localhost:11434/v1")


def test_bad_specs_are_rejected_before_any_import() -> None:
    with pytest.raises(InvalidModelSpec):
        create_translator("llama3.1:8b")


@pytest.mark.parametrize(
    ("spec", "module", "extra"),
    [
        ("claude=claude-opus-5", "anthropic", "claude"),
        ("openai=gpt-5-mini", "openai", "openai"),
        ("gemini=gemini-2.5-flash", "google.genai", "gemini"),
        ("openrouter=openai/gpt-5-mini", "openai", "openrouter"),
    ],
)
def test_a_missing_sdk_names_the_extra_to_install(
    spec: str, module: str, extra: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, module, None)
    with pytest.raises(ProviderNotInstalled) as caught:
        create_translator(spec)
    assert caught.value.extra == extra
    assert f'pip install "u-transcript-max[{extra}]"' in str(caught.value)
    assert isinstance(caught.value, MissingExtra)
    assert isinstance(caught.value, ImportError)
