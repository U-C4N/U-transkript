"""Tests for the Claude translator (fake client, real anthropic types)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.sdk import FakeAnthropic, api_error, claude_message
from utmax.adapters.providers.base import redact_secrets
from utmax.adapters.providers.claude import ClaudeTranslator
from utmax.core.translate.batching import InvalidResponse
from utmax.core.translate.protocol import response_schema
from utmax.errors import (
    InvalidOption,
    ProviderAuthError,
    ProviderError,
    ProviderNotInstalled,
    ProviderRateLimited,
    TranslationError,
    TranslationRefused,
)
from utmax.models import Segment
from utmax.services.translation import translate_transcript

anthropic = pytest.importorskip("anthropic")

SYSTEM = "You translate subtitles."
PROMPT = '{"items": [{"id": 0, "text": "Hello."}]}'
SCHEMA = {"type": "object"}
ANSWER = '{"items": [{"id": 0, "text": "Merhaba."}]}'


def claude(*replies: object, **options: object) -> tuple[ClaudeTranslator, FakeAnthropic]:
    client = FakeAnthropic(*replies)
    return ClaudeTranslator("claude-opus-5", client=client, **options), client  # type: ignore[arg-type]


def test_the_request_asks_for_json_matching_the_schema() -> None:
    translator, client = claude(claude_message(ANSWER))
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    assert client.create.calls == [
        {
            "model": "claude-opus-5",
            "max_tokens": 16000,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": PROMPT}],
            "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        }
    ]


def test_effort_and_max_tokens_are_passed_on() -> None:
    translator, client = claude(claude_message(ANSWER), effort="low", max_tokens=8000)
    translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    (call,) = client.create.calls
    assert call["max_tokens"] == 8000
    assert call["output_config"] == {
        "format": {"type": "json_schema", "schema": SCHEMA},
        "effort": "low",
    }


@pytest.mark.parametrize("options", [{"effort": "extreme"}, {"max_tokens": 0}, {"model": " "}])
def test_bad_options_are_rejected(options: dict[str, object]) -> None:
    arguments: dict[str, object] = {"model": "claude-opus-5", "client": FakeAnthropic()}
    with pytest.raises(InvalidOption):
        ClaudeTranslator(**(arguments | options))  # type: ignore[arg-type]


def test_thinking_blocks_are_skipped() -> None:
    translator, _ = claude(claude_message(ANSWER, thinking=True))
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER


def test_a_refusal_wins_over_any_text() -> None:
    translator, _ = claude(claude_message(ANSWER, stop_reason="refusal", refusal="cyber"))
    with pytest.raises(TranslationRefused, match="cyber") as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.provider == "claude"


@pytest.mark.parametrize("stop_reason", ["max_tokens", "model_context_window_exceeded"])
def test_a_cut_off_answer_is_invalid(stop_reason: str) -> None:
    translator, _ = claude(claude_message('{"items": [', stop_reason=stop_reason))
    with pytest.raises(InvalidResponse, match=stop_reason) as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.raw == '{"items": ['


@pytest.mark.parametrize(
    ("name", "status", "expected"),
    [
        ("AuthenticationError", 401, ProviderAuthError),
        ("PermissionDeniedError", 403, ProviderAuthError),
        ("RateLimitError", 429, ProviderRateLimited),
        ("BadRequestError", 400, ProviderError),
        ("NotFoundError", 404, ProviderError),
        ("InternalServerError", 500, ProviderError),
        ("OverloadedError", 529, ProviderError),
        ("APIConnectionError", 0, ProviderError),
        ("APITimeoutError", 0, ProviderError),
    ],
)
def test_sdk_errors_are_mapped(name: str, status: int, expected: type[TranslationError]) -> None:
    translator, _ = claude(api_error(anthropic, name, status))
    with pytest.raises(expected) as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert type(caught.value) is expected
    assert caught.value.provider == "claude"
    assert isinstance(caught.value.__cause__, getattr(anthropic, name))
    if isinstance(caught.value, ProviderError):
        assert caught.value.status_code == (status or None)


@pytest.mark.parametrize(
    "error",
    [
        TypeError(
            '"Could not resolve authentication method. Expected one of api_key, auth_token, or '
            'credentials to be set."'
        ),
        anthropic.CredentialsError("Config file not found (profile 'default')."),
    ],
)
def test_missing_credentials_name_the_environment_variable(error: Exception) -> None:
    translator, _ = claude(error)
    with pytest.raises(ProviderAuthError) as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert "ANTHROPIC_API_KEY" in caught.value.suggestion
    assert caught.value.__cause__ is error


def test_a_missing_profile_is_reported_when_the_client_is_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ProviderAuthError) as caught:
        ClaudeTranslator("claude-opus-5")
    assert isinstance(caught.value.__cause__, anthropic.CredentialsError)


def test_other_type_errors_are_not_hidden() -> None:
    translator, _ = claude(TypeError("unexpected keyword"))
    with pytest.raises(TypeError, match="unexpected keyword"):
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)


def test_sdk_errors_that_are_not_api_failures_are_not_hidden() -> None:
    translator, _ = claude(anthropic.AnthropicError("odd failure"))
    with pytest.raises(anthropic.AnthropicError, match="odd failure"):
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)


def test_keys_never_reach_error_messages() -> None:
    leaked = "invalid x-api-key sk-ant-api03-SECRETSECRET"
    translator, _ = claude(api_error(anthropic, "AuthenticationError", 401, leaked))
    with pytest.raises(ProviderAuthError) as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert "SECRET" not in str(caught.value)
    assert "[redacted]" in str(caught.value)
    assert redact_secrets("key AIzaSyA1234567890abcdefghijkl") == "key [redacted]"


def test_a_real_client_is_built_without_exposing_the_key() -> None:
    translator = ClaudeTranslator("claude-opus-5", api_key="sk-ant-api03-SECRETSECRET")
    assert translator.name == "claude=claude-opus-5"
    assert repr(translator) == "ClaudeTranslator('claude=claude-opus-5')"
    assert "SECRET" not in repr(vars(translator).get("_client"))


def test_a_missing_sdk_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ProviderNotInstalled) as caught:
        ClaudeTranslator("claude-opus-5")
    assert (caught.value.provider, caught.value.extra) == ("claude", "claude")
    assert 'pip install "u-transcript-max[claude]"' in str(caught.value)
    assert isinstance(caught.value, ImportError)


def test_the_engine_translates_through_claude() -> None:
    translator, client = claude(claude_message(ANSWER))
    result = translate_transcript(make_transcript(Segment(0.0, 1.0, "Hello.")), "tr", translator)
    assert (result.text, result.translator) == ("Merhaba.", "claude=claude-opus-5")
    (call,) = client.create.calls
    assert json.loads(call["messages"][0]["content"])["items"] == [{"id": 0, "text": "Hello."}]
    assert call["output_config"]["format"]["schema"] == response_schema()
