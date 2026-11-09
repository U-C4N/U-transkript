"""Tests for create_translator: provider specs to translator instances."""

from __future__ import annotations

import sys

import pytest

from tests.helpers.sdk import FakeAnthropic, FakeGenAI, FakeOpenAI
from utmax.adapters.providers import (
    TRANSLATORS,
    ClaudeTranslator,
    GeminiTranslator,
    GrokTranslator,
    OpenAITranslator,
    OpenRouterTranslator,
    create_translator,
)
from utmax.core.translate.spec import PROVIDERS
from utmax.errors import InvalidModelSpec, InvalidOption, MissingExtra, ProviderNotInstalled


@pytest.mark.parametrize(
    ("spec", "module", "cls", "fake"),
    [
        ("claude=claude-opus-5-5", "anthropic", ClaudeTranslator, FakeAnthropic),
        ("openai=llama3.1:8b", "openai", OpenAITranslator, FakeOpenAI),
        ("gemini=gemini-3.8-flash", "google.genai", GeminiTranslator, FakeGenAI),
        ("gemini=gemini-4-argon", "google.genai", GeminiTranslator, FakeGenAI),
        ("grok=grok-4.7", "openai", GrokTranslator, FakeOpenAI),
        ("openrouter=openai/gpt-6-astra", "openai", OpenRouterTranslator, FakeOpenAI),
    ],
)
def test_every_provider_gets_its_translator(spec: str, module: str, cls: type, fake: type) -> None:
    pytest.importorskip(module)
    translator = create_translator(spec, client=fake(), batch_items=10)
    assert type(translator) is cls
    assert translator.name == spec
    assert translator.batch_items == 10


def test_the_registry_covers_every_provider() -> None:
    assert (
        set(TRANSLATORS) == set(PROVIDERS) == {"claude", "openai", "gemini", "grok", "openrouter"}
    )


@pytest.mark.parametrize(
    ("spec", "module", "fake", "allowed"),
    [
        ("claude=claude-opus-5-5", "anthropic", FakeAnthropic, "low, medium, high, xhigh, max"),
        ("openai=gpt-6-astra", "openai", FakeOpenAI, "low, medium, high, xhigh"),
        ("gemini=gemini-4-argon", "google.genai", FakeGenAI, "low, medium, high"),
        ("grok=grok-4.7", "openai", FakeOpenAI, "low, medium, high, xhigh"),
        ("openrouter=openai/gpt-6-astra", "openai", FakeOpenAI, "low, medium, high"),
    ],
)
def test_every_provider_takes_effort_and_names_the_values_it_accepts(
    spec: str, module: str, fake: type, allowed: str
) -> None:
    pytest.importorskip(module)
    assert create_translator(spec, client=fake(), effort="low").effort == "low"  # type: ignore[attr-defined]
    with pytest.raises(InvalidOption, match=f"effort must be one of {allowed}, not 'turbo'"):
        create_translator(spec, client=fake(), effort="turbo")


def test_base_url_only_works_with_openai() -> None:
    with pytest.raises(InvalidOption, match="only works with the openai provider"):
        create_translator("claude=claude-opus-5-5", base_url="http://localhost:11434/v1")


def test_bad_specs_are_rejected_before_any_import() -> None:
    with pytest.raises(InvalidModelSpec):
        create_translator("llama3.1:8b")


@pytest.mark.parametrize(
    ("spec", "module", "extra"),
    [
        ("claude=claude-opus-5-5", "anthropic", "claude"),
        ("openai=gpt-6-astra", "openai", "openai"),
        ("gemini=gemini-3.8-flash", "google.genai", "gemini"),
        ("grok=grok-4.7", "openai", "grok"),
        ("openrouter=openai/gpt-6-astra", "openai", "openrouter"),
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
