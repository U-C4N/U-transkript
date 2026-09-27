"""Tests for translate, translator and bilingual on utmax.Client and the utmax facade."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import utmax
import utmax.providers
from tests.helpers.builders import make_transcript
from tests.helpers.fake_translator import FakeTranslator
from tests.helpers.fake_transport import FakeTransport
from tests.helpers.sdk import FakeOpenAI, openai_completion
from utmax.models import Segment

MANUAL = make_transcript(Segment(1.0, 2.0, "Hello there."), Segment(3.0, 2.0, "Bye."))


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the facade use a Client that cannot reach the network."""
    monkeypatch.setattr(utmax, "_default_client", utmax.Client(transport=FakeTransport()))


def test_the_client_translates_and_combines() -> None:
    client = utmax.Client(transport=FakeTransport())
    translation = client.translate(MANUAL, "tr", model=FakeTranslator(), instructions="Formal.")
    assert [segment.text for segment in translation] == ["HELLO THERE.", "BYE."]
    combined = client.bilingual(MANUAL, translation)
    assert (combined.language_code, combined[0].text) == ("en+tr", "Hello there.\nHELLO THERE.")


def test_translations_save_in_every_format(tmp_path: Path) -> None:
    client = utmax.Client(transport=FakeTransport())
    translation = client.translate(MANUAL, "tr", model=FakeTranslator())
    for name in ("rick.tr.srt", "rick.tr.vtt", "rick.tr.json", "rick.tr.txt"):
        assert "HELLO THERE." in translation.save(tmp_path / name).read_text(encoding="utf-8")
    data = json.loads((tmp_path / "rick.tr.json").read_text(encoding="utf-8"))
    assert (data["language_code"], data["language"]) == ("tr", "Turkish")
    assert (data["translated_from"], data["translator"]) == ("en", "fake=echo-1")
    assert translation.to("pretty") == "[00:01] HELLO THERE.\n[00:03] BYE.\n"


@pytest.mark.usefixtures("offline")
def test_module_functions_translate_and_combine() -> None:
    translator = FakeTranslator()
    translation = utmax.translate(MANUAL, "de", model=translator, resegment=True)
    assert translation.translator == "fake=echo-1"
    assert translator.requests[0]["target_language"] == {"code": "de", "name": "German"}
    combined = utmax.bilingual(MANUAL, translation, translation_first=True)
    assert combined[1].text == "BYE.\nBye."


@pytest.mark.usefixtures("offline")
def test_a_model_string_builds_the_translator_with_its_options() -> None:
    pytest.importorskip("openai")
    answer = json.dumps({"items": [{"id": 0, "text": "Hallo."}, {"id": 1, "text": "Tschuss."}]})
    fake = FakeOpenAI(openai_completion(answer))
    translation = utmax.translate(
        MANUAL,
        "de",
        model="openai=llama3.1:8b",
        base_url="http://localhost:11434/v1",
        client=fake,
        batch_items=10,
    )
    assert (translation.text, translation.translator) == ("Hallo. Tschuss.", "openai=llama3.1:8b")
    assert fake.create.calls[0]["model"] == "llama3.1:8b"


@pytest.mark.usefixtures("offline")
def test_translator_builds_an_ollama_translator_without_any_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    translator = utmax.translator("openai=llama3.1:8b", base_url="http://localhost:11434/v1")
    assert isinstance(translator, utmax.providers.OpenAITranslator)
    assert translator.name == "openai=llama3.1:8b"
    assert utmax.Client(transport=FakeTransport()).translator(
        "openai=llama3.1:8b", base_url="http://localhost:11434/v1"
    ).name == ("openai=llama3.1:8b")


@pytest.mark.usefixtures("offline")
def test_options_cannot_be_combined_with_a_translator_instance() -> None:
    with pytest.raises(utmax.InvalidOption, match="only apply when model is"):
        utmax.translate(MANUAL, "tr", model=FakeTranslator(), effort="low")


@pytest.mark.usefixtures("offline")
@pytest.mark.parametrize("model", ["", "claude", "gpt-5-mini", "anthropic=claude-opus-5", None])
def test_bad_model_specs_raise(model: str) -> None:
    with pytest.raises(utmax.InvalidModelSpec):
        utmax.translate(MANUAL, "tr", model=model)
    with pytest.raises(utmax.InvalidModelSpec):
        utmax.translator(model)


def test_the_translation_api_is_public() -> None:
    names = {
        "translate",
        "translator",
        "bilingual",
        "Translator",
        "InvalidModelSpec",
        "MissingExtra",
        "TranslationError",
        "ProviderNotInstalled",
        "ProviderAuthError",
        "ProviderRateLimited",
        "ProviderError",
        "TranslationRefused",
        "TranslationMismatch",
    }
    assert names <= set(utmax.__all__)
    assert set(utmax.providers.__all__) == {
        "ClaudeTranslator",
        "EngineOptions",
        "GeminiTranslator",
        "InvalidResponse",
        "JsonMode",
        "OpenAITranslator",
        "OpenRouterTranslator",
        "Translator",
    }
    for name in utmax.providers.__all__:
        assert hasattr(utmax.providers, name), name


def test_importing_utmax_loads_no_provider_sdk_even_when_installed() -> None:
    probe = (
        "import sys, utmax, utmax.providers\n"
        "loaded = [m for m in ('anthropic', 'openai', 'google.genai', 'httpx', 'httpx2')"
        " if m in sys.modules]\n"
        "print(loaded)\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV_", "COVERAGE_"))}
    env["PYTHONPATH"] = str(Path(utmax.__file__).resolve().parent.parent)
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, check=True
    )
    assert result.stdout.strip() == "[]"
