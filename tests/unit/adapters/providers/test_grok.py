"""Tests for the Grok translator (fake client, real openai types)."""

from __future__ import annotations

import sys

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.sdk import FakeOpenAI, api_error, openai_completion
from utmax.adapters.providers.base import redact_secrets
from utmax.adapters.providers.grok import XAI_BASE_URL, GrokTranslator
from utmax.errors import (
    InvalidOption,
    ProviderAuthError,
    ProviderNotInstalled,
    ProviderRateLimited,
)
from utmax.models import Segment
from utmax.services.translation import translate_transcript

openai = pytest.importorskip("openai")

SYSTEM = "You translate subtitles."
PROMPT = '{"items": [{"id": 0, "text": "Hello."}]}'
SCHEMA = {"type": "object"}
ANSWER = '{"items": [{"id": 0, "text": "Merhaba."}]}'


def test_requests_ask_for_strict_json_without_routing_extras() -> None:
    client = FakeOpenAI(openai_completion(ANSWER))
    translator = GrokTranslator("grok-4.7", client=client)
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    (call,) = client.create.calls
    assert call["model"] == "grok-4.7"
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True
    assert "extra_body" not in call
    assert "reasoning_effort" not in call
    assert translator.name == "grok=grok-4.7"
    assert repr(translator) == "GrokTranslator('grok=grok-4.7')"


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh"])
def test_effort_is_sent_as_reasoning_effort(effort: str) -> None:
    client = FakeOpenAI(openai_completion(ANSWER))
    GrokTranslator("grok-4.7", effort=effort, client=client).generate_json(SYSTEM, PROMPT, SCHEMA)
    assert client.create.calls[0]["reasoning_effort"] == effort


def test_max_effort_is_not_a_grok_value() -> None:
    with pytest.raises(InvalidOption, match="low, medium, high, xhigh"):
        GrokTranslator("grok-4.7", effort="max", client=FakeOpenAI())


def test_the_json_mode_steps_down_on_xai_too() -> None:
    rejected = api_error(openai, "BadRequestError", 400, "response_format json_schema unsupported")
    client = FakeOpenAI(rejected, openai_completion(ANSWER))
    translator = GrokTranslator("grok-4.7", client=client)
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    assert client.create.calls[1]["response_format"] == {"type": "json_object"}


def test_the_key_comes_from_xai_api_key_never_from_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-OPENAIKEY123")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(ProviderAuthError) as caught:
        GrokTranslator("grok-4.7")
    assert "XAI_API_KEY" in caught.value.suggestion
    assert caught.value.provider == "grok"
    monkeypatch.setenv("XAI_API_KEY", "xai-FROMENVIRONMENT")
    client = vars(GrokTranslator("grok-4.7"))["_client"]
    assert client.api_key == "xai-FROMENVIRONMENT"
    assert str(client.base_url) == f"{XAI_BASE_URL}/"


def test_an_explicit_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-FROMENVIRONMENT")
    translator = GrokTranslator("grok-4.7", api_key="xai-EXPLICITKEY")
    assert vars(translator)["_client"].api_key == "xai-EXPLICITKEY"


def test_errors_name_xai() -> None:
    client = FakeOpenAI(api_error(openai, "RateLimitError", 429))
    translator = GrokTranslator("grok-4.7", client=client)
    with pytest.raises(ProviderRateLimited, match="xAI") as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.provider == "grok"


def test_xai_keys_never_reach_error_messages() -> None:
    assert redact_secrets("bad key xai-AbCdEf0123456789") == "bad key [redacted]"


def test_a_missing_sdk_names_the_grok_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ProviderNotInstalled) as caught:
        GrokTranslator("grok-4.7")
    assert (caught.value.provider, caught.value.extra) == ("grok", "grok")
    assert 'pip install "u-transcript-max[grok]"' in str(caught.value)


def test_the_engine_translates_through_grok() -> None:
    translator = GrokTranslator("grok-4.7", client=FakeOpenAI(openai_completion(ANSWER)))
    result = translate_transcript(make_transcript(Segment(0.0, 1.0, "Hello.")), "tr", translator)
    assert (result.text, result.translator) == ("Merhaba.", "grok=grok-4.7")
