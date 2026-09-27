"""Tests for the Gemini translator (fake client, real google-genai types)."""

from __future__ import annotations

import sys

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.sdk import FakeGenAI, gemini_error, gemini_response
from utmax.adapters.providers.gemini import GeminiTranslator
from utmax.core.translate.batching import InvalidResponse
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

types = pytest.importorskip("google.genai.types")
httpx = pytest.importorskip("httpx")

SYSTEM = "You translate subtitles."
PROMPT = '{"items": [{"id": 0, "text": "Hello."}]}'
SCHEMA = {"type": "object"}
ANSWER = '{"items": [{"id": 0, "text": "Bonjour."}]}'


def gemini(*replies: object, **options: object) -> tuple[GeminiTranslator, FakeGenAI]:
    client = FakeGenAI(*replies)
    return GeminiTranslator("gemini-2.5-flash", client=client, **options), client  # type: ignore[arg-type]


def test_the_request_asks_for_json_matching_the_schema_with_retries() -> None:
    translator, client = gemini(gemini_response(ANSWER))
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    (call,) = client.generate.calls
    assert (call["model"], call["contents"]) == ("gemini-2.5-flash", PROMPT)
    config = call["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.system_instruction == SYSTEM
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SCHEMA
    assert config.http_options.retry_options.attempts == 5
    assert config.automatic_function_calling.disable is True


def test_retry_attempts_are_configurable() -> None:
    translator, client = gemini(gemini_response(ANSWER), retry_attempts=2)
    translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert client.generate.calls[0]["config"].http_options.retry_options.attempts == 2
    with pytest.raises(InvalidOption, match="retry_attempts"):
        GeminiTranslator("gemini-2.5-flash", retry_attempts=0, client=FakeGenAI())


def test_thought_parts_are_skipped() -> None:
    translator, _ = gemini(gemini_response(ANSWER, thought="Let me think."))
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER


def test_a_blocked_prompt_raises_translation_refused() -> None:
    translator, _ = gemini(gemini_response(None, block_reason="SAFETY"))
    with pytest.raises(TranslationRefused, match="SAFETY") as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.provider == "gemini"


@pytest.mark.parametrize("finish_reason", ["SAFETY", "RECITATION", "PROHIBITED_CONTENT"])
def test_safety_stops_raise_translation_refused(finish_reason: str) -> None:
    translator, _ = gemini(gemini_response("", finish_reason=finish_reason))
    with pytest.raises(TranslationRefused, match=finish_reason):
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)


def test_a_cut_off_answer_is_invalid() -> None:
    translator, _ = gemini(gemini_response('{"items": [', finish_reason="MAX_TOKENS"))
    with pytest.raises(InvalidResponse, match="MAX_TOKENS") as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.raw == '{"items": ['


def test_an_answer_without_candidates_is_empty() -> None:
    translator, _ = gemini(types.GenerateContentResponse(candidates=[]))
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ""


@pytest.mark.parametrize(
    ("error", "expected", "status_code"),
    [
        (gemini_error(401, "UNAUTHENTICATED"), ProviderAuthError, None),
        (gemini_error(403, "PERMISSION_DENIED"), ProviderAuthError, None),
        (gemini_error(400, "INVALID_ARGUMENT", "API key not valid."), ProviderAuthError, None),
        (gemini_error(429, "RESOURCE_EXHAUSTED"), ProviderRateLimited, None),
        (gemini_error(404, "NOT_FOUND", "models/x is not found"), ProviderError, 404),
        (gemini_error(503, "UNAVAILABLE"), ProviderError, 503),
    ],
)
def test_api_errors_are_mapped(
    error: Exception, expected: type[TranslationError], status_code: int | None
) -> None:
    translator, _ = gemini(error)
    with pytest.raises(expected) as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert type(caught.value) is expected
    assert caught.value.provider == "gemini"
    assert caught.value.__cause__ is error
    if isinstance(caught.value, ProviderError):
        assert caught.value.status_code == status_code


def test_network_failures_are_provider_errors() -> None:
    translator, _ = gemini(httpx.ConnectError("connection refused"))
    with pytest.raises(ProviderError, match="Could not reach Gemini") as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.status_code is None


def test_keys_never_reach_error_messages() -> None:
    leaked = gemini_error(
        400, "INVALID_ARGUMENT", "API key not valid: AIzaSyA1234567890abcdefghijk"
    )
    translator, _ = gemini(leaked)
    with pytest.raises(ProviderAuthError) as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert "AIzaSy" not in str(caught.value)


def test_without_a_key_the_error_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_GENAI_USE_ENTERPRISE",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderAuthError) as caught:
        GeminiTranslator("gemini-2.5-flash")
    assert "GEMINI_API_KEY" in caught.value.suggestion
    assert isinstance(caught.value.__cause__, ValueError)


def test_a_real_client_is_built_from_the_key() -> None:
    translator = GeminiTranslator("gemini-2.5-flash", api_key="AIzaFAKEKEYFORTESTS")
    assert translator.name == "gemini=gemini-2.5-flash"
    assert repr(translator) == "GeminiTranslator('gemini=gemini-2.5-flash')"


def test_a_missing_sdk_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "google.genai", None)
    with pytest.raises(ProviderNotInstalled) as caught:
        GeminiTranslator("gemini-2.5-flash")
    assert (caught.value.provider, caught.value.extra) == ("gemini", "gemini")
    assert 'pip install "u-transcript-max[gemini]"' in str(caught.value)


def test_the_engine_translates_through_gemini() -> None:
    translator, _ = gemini(gemini_response(ANSWER))
    result = translate_transcript(make_transcript(Segment(0.0, 1.0, "Hello.")), "fr", translator)
    assert (result.text, result.translator) == ("Bonjour.", "gemini=gemini-2.5-flash")
