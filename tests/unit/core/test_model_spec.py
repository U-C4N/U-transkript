"""Tests for the "provider=model-id" parser."""

from __future__ import annotations

import pytest

from utmax.core.translate.spec import PROVIDERS, ModelSpec, parse_model_spec
from utmax.errors import InvalidModelSpec


@pytest.mark.parametrize(
    ("spec", "provider", "model"),
    [
        ("claude=claude-opus-5", "claude", "claude-opus-5"),
        ("openai=llama3.1:8b", "openai", "llama3.1:8b"),
        ("gemini=gemini-2.5-flash", "gemini", "gemini-2.5-flash"),
        ("openrouter=meta-llama/llama-4-maverick", "openrouter", "meta-llama/llama-4-maverick"),
        ("openai=org=model", "openai", "org=model"),
        ("  Claude = claude-opus-5 ", "claude", "claude-opus-5"),
    ],
)
def test_valid_specs(spec: str, provider: str, model: str) -> None:
    assert parse_model_spec(spec) == ModelSpec(provider, model)


def test_a_spec_prints_as_provider_equals_model() -> None:
    assert str(parse_model_spec("OpenAI=gpt-5-mini")) == "openai=gpt-5-mini"
    assert PROVIDERS == ("claude", "openai", "gemini", "openrouter")


@pytest.mark.parametrize(
    ("spec", "reason"),
    [
        ("", "provider=model-id"),
        ("claude", "provider=model-id"),
        ("gpt-5-mini", "provider=model-id"),
        ("claude=", "provider=model-id"),
        ("=claude-opus-5", "provider=model-id"),
        ("claude= ", "provider=model-id"),
        ("anthropic=claude-opus-5", "Unknown provider 'anthropic'"),
        ("ollama=llama3.1:8b", "choose one of: claude, openai, gemini, openrouter"),
        (None, "must be a string"),
        (42, "must be a string"),
    ],
)
def test_invalid_specs(spec: object, reason: str) -> None:
    with pytest.raises(InvalidModelSpec, match=reason) as caught:
        parse_model_spec(spec)
    assert isinstance(caught.value, ValueError)
