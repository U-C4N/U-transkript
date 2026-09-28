"""Tests for the OpenAI translator (fake client, real openai types)."""

from __future__ import annotations

import sys

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.sdk import FakeOpenAI, api_error, openai_completion
from utmax.adapters.providers.openai import OpenAITranslator
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

openai = pytest.importorskip("openai")

SYSTEM = "You translate subtitles."
PROMPT = '{"items": [{"id": 0, "text": "Hello."}]}'
SCHEMA = {"type": "object"}
ANSWER = '{"items": [{"id": 0, "text": "Hallo."}]}'
JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {"name": "subtitle_translation", "schema": SCHEMA, "strict": True},
}


def gpt(*replies: object, **options: object) -> tuple[OpenAITranslator, FakeOpenAI]:
    client = FakeOpenAI(*replies)
    return OpenAITranslator("gpt-5-mini", client=client, **options), client  # type: ignore[arg-type]


def rejected(message: str = "response_format json_schema is not supported") -> Exception:
    return api_error(openai, "BadRequestError", 400, message)


def test_the_request_uses_strict_structured_outputs() -> None:
    translator, client = gpt(openai_completion(ANSWER))
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    assert client.create.calls == [
        {
            "model": "gpt-5-mini",
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": PROMPT},
            ],
            "response_format": JSON_SCHEMA,
        }
    ]
    assert translator.mode == "json_schema"


def test_auto_steps_down_to_json_object_and_remembers_it() -> None:
    translator, client = gpt(rejected(), openai_completion(ANSWER))
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    formats = [call.get("response_format") for call in client.create.calls]
    assert formats == [JSON_SCHEMA, {"type": "json_object"}, {"type": "json_object"}]
    system = client.create.calls[1]["messages"][0]["content"]
    assert system.startswith(SYSTEM)
    assert system.endswith('matches this JSON Schema:\n{"type": "object"}')
    assert translator.mode == "json_object"


def test_auto_ends_with_prompt_only_requests() -> None:
    translator, client = gpt(
        rejected(),
        rejected("'response_format.type' must be 'json_schema' or 'text'"),
        openai_completion(ANSWER),
    )
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    assert "response_format" not in client.create.calls[2]
    assert translator.mode == "prompt"


def test_unprocessable_entity_answers_step_down_too() -> None:
    error = api_error(openai, "UnprocessableEntityError", 422, "json_schema: unknown field")
    translator, client = gpt(error, openai_completion(ANSWER))
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ANSWER
    assert client.create.calls[1]["response_format"] == {"type": "json_object"}


def test_other_bad_requests_are_errors() -> None:
    translator, client = gpt(rejected("maximum context length exceeded"))
    with pytest.raises(ProviderError) as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.status_code == 400
    assert len(client.create.calls) == 1
    assert translator.mode == "json_schema"


@pytest.mark.parametrize("json_mode", ["json_schema", "json_object", "prompt"])
def test_explicit_modes_never_step_down(json_mode: str) -> None:
    translator, client = gpt(rejected(), json_mode=json_mode)
    with pytest.raises(ProviderError):
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert len(client.create.calls) == 1


def test_explicit_modes_shape_the_request() -> None:
    translator, client = gpt(openai_completion(ANSWER), json_mode="json_object")
    translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert client.create.calls[0]["response_format"] == {"type": "json_object"}
    translator, client = gpt(openai_completion(ANSWER), json_mode="prompt")
    translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert "response_format" not in client.create.calls[0]


def test_parallel_rejections_step_down_only_once() -> None:
    translator, _ = gpt(openai_completion(ANSWER))
    translator._step_down("json_schema")
    translator._step_down("json_schema")
    assert translator.mode == "json_object"


def test_an_unknown_json_mode_is_rejected() -> None:
    with pytest.raises(InvalidOption, match="json_mode"):
        OpenAITranslator("gpt-5-mini", json_mode="yaml", client=FakeOpenAI())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("completion", "reason"),
    [
        (openai_completion(None, refusal="I can't help with that."), "can't help"),
        (openai_completion("", finish_reason="content_filter"), "content filter"),
    ],
)
def test_refusals_raise_translation_refused(completion: object, reason: str) -> None:
    translator, _ = gpt(completion)
    with pytest.raises(TranslationRefused, match=reason) as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.provider == "openai"


def test_cut_off_and_empty_answers_are_invalid() -> None:
    translator, _ = gpt(openai_completion('{"items": [', finish_reason="length"))
    with pytest.raises(InvalidResponse, match="cut off") as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert caught.value.raw == '{"items": ['
    translator, _ = gpt(openai_completion(ANSWER, choices=False))
    with pytest.raises(InvalidResponse, match="no choices"):
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    translator, _ = gpt(openai_completion(None))
    assert translator.generate_json(SYSTEM, PROMPT, SCHEMA) == ""


@pytest.mark.parametrize(
    ("name", "status", "expected"),
    [
        ("AuthenticationError", 401, ProviderAuthError),
        ("PermissionDeniedError", 403, ProviderAuthError),
        ("RateLimitError", 429, ProviderRateLimited),
        ("NotFoundError", 404, ProviderError),
        ("InternalServerError", 500, ProviderError),
        ("APIConnectionError", 0, ProviderError),
        ("APITimeoutError", 0, ProviderError),
    ],
)
def test_sdk_errors_are_mapped(name: str, status: int, expected: type[TranslationError]) -> None:
    translator, _ = gpt(api_error(openai, name, status))
    with pytest.raises(expected) as caught:
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)
    assert type(caught.value) is expected
    assert caught.value.provider == "openai"
    assert "OpenAI" in str(caught.value)
    assert isinstance(caught.value.__cause__, getattr(openai, name))


def test_sdk_errors_that_are_not_api_failures_are_not_hidden() -> None:
    translator, _ = gpt(openai.OpenAIError("odd failure"))
    with pytest.raises(openai.OpenAIError, match="odd failure"):
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)


def test_a_local_server_needs_no_key_and_never_gets_the_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-REALKEY123456")
    translator = OpenAITranslator("llama3.1:8b", base_url="http://localhost:11434/v1")
    client = vars(translator)["_client"]
    assert client.api_key == "not-needed"
    assert str(client.base_url) == "http://localhost:11434/v1/"
    assert translator.name == "openai=llama3.1:8b"


def test_a_custom_server_gets_the_key_passed_to_it() -> None:
    translator = OpenAITranslator(
        "llama-3.3-70b", api_key="gsk_test", base_url="https://api.groq.com/openai/v1"
    )
    assert vars(translator)["_client"].api_key == "gsk_test"


def test_errors_from_a_custom_server_name_it() -> None:
    translator = OpenAITranslator(
        "llama3.1:8b",
        base_url="http://localhost:11434/v1",
        client=FakeOpenAI(api_error(openai, "InternalServerError", 500)),
    )
    with pytest.raises(ProviderError, match="the server at http://localhost:11434/v1"):
        translator.generate_json(SYSTEM, PROMPT, SCHEMA)


def test_without_any_key_the_error_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    with pytest.raises(ProviderAuthError) as caught:
        OpenAITranslator("gpt-5-mini")
    assert "OPENAI_API_KEY" in caught.value.suggestion
    assert isinstance(caught.value.__cause__, openai.OpenAIError)


def test_a_missing_sdk_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ProviderNotInstalled) as caught:
        OpenAITranslator("gpt-5-mini")
    assert (caught.value.provider, caught.value.extra) == ("openai", "openai")
    assert 'pip install "u-transcript-max[openai]"' in str(caught.value)


def test_the_engine_translates_through_openai() -> None:
    translator, _ = gpt(openai_completion(ANSWER))
    result = translate_transcript(make_transcript(Segment(0.0, 1.0, "Hello.")), "de", translator)
    assert (result.text, result.translator) == ("Hallo.", "openai=gpt-5-mini")
