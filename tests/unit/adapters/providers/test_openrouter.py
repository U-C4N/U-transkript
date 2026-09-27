"""Tests for the OpenRouter translator (fake client, real openai types)."""

from __future__ import annotations

import sys

import pytest

from tests.helpers.sdk import FakeOpenAI, api_error, openai_completion
from utmax.adapters.providers.openrouter import OPENROUTER_BASE_URL, OpenRouterTranslator
from utmax.errors import ProviderAuthError, ProviderNotInstalled, ProviderRateLimited

openai = pytest.importorskip("openai")

SYSTEM = "You translate subtitles."
PROMPT = '{"items": [{"id": 0, "text": "Hello."}]}'
SCHEMA = {"type": "object"}
ANSWER = '{"items": [{"id": 0, "text": "Hola."}]}'
ROUTING = {"provider": {"require_parameters": True}}


def test_requests_take_the_openai_path_and_require_every_parameter() -> None:
    client = FakeOpenAI(openai_completion(ANSWER))
    translator = OpenRouterTranslator("anthropic/claude-opus-5", client=client)
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    (call,) = client.create.calls
    assert call["model"] == "anthropic/claude-opus-5"
    assert call["response_format"]["type"] == "json_schema"
    assert call["extra_body"] == ROUTING
    assert translator.name == "openrouter=anthropic/claude-opus-5"


def test_the_json_mode_steps_down_on_openrouter_too() -> None:
    rejected = api_error(openai, "BadRequestError", 400, "response_format is not supported")
    client = FakeOpenAI(rejected, openai_completion(ANSWER))
    translator = OpenRouterTranslator("meta-llama/llama-4-maverick", client=client)
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    assert client.create.calls[1]["response_format"] == {"type": "json_object"}
    assert all(call["extra_body"] == ROUTING for call in client.create.calls)


def test_the_key_comes_from_openrouter_api_key_never_from_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-OPENAIKEY123")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ProviderAuthError) as caught:
        OpenRouterTranslator("openai/gpt-5-mini")
    assert "OPENROUTER_API_KEY" in caught.value.suggestion
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-ROUTERKEY")
    client = vars(OpenRouterTranslator("openai/gpt-5-mini", app_name="Subtitle App"))["_client"]
    assert client.api_key == "sk-or-v1-ROUTERKEY"
    assert str(client.base_url) == f"{OPENROUTER_BASE_URL}/"
    assert client.default_headers["X-Title"] == "Subtitle App"


def test_an_explicit_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-FROMENV")
    translator = OpenRouterTranslator("openai/gpt-5-mini", api_key="sk-or-v1-EXPLICIT")
    assert vars(translator)["_client"].api_key == "sk-or-v1-EXPLICIT"


def test_errors_name_openrouter() -> None:
    client = FakeOpenAI(api_error(openai, "RateLimitError", 429))
    translator = OpenRouterTranslator("openai/gpt-5-mini", client=client)
    with pytest.raises(ProviderRateLimited, match="OpenRouter") as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.provider == "openrouter"


def test_a_missing_sdk_names_the_openrouter_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ProviderNotInstalled) as caught:
        OpenRouterTranslator("openai/gpt-5-mini")
    assert (caught.value.provider, caught.value.extra) == ("openrouter", "openrouter")
    assert 'pip install "u-transcript-max[openrouter]"' in str(caught.value)
