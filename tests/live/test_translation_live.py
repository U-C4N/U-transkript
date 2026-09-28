"""Live AI translation checks (spec section 8.10); each runs only when its provider key is set.

Run with ``uv run pytest -m live tests/live/test_translation_live.py -v``. The model of each
provider can be overridden with ``UTMAX_LIVE_<PROVIDER>_MODEL``, for example
``UTMAX_LIVE_OPENAI_MODEL=gpt-5-mini``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import utmax
from tests.helpers.builders import make_transcript
from utmax.models import Segment

pytestmark = pytest.mark.live

SOURCE = make_transcript(
    Segment(0.0, 2.0, "We're no strangers to love."),
    Segment(2.0, 2.5, "You know the rules\nand so do I."),
    Segment(4.5, 2.0, "[Music]"),
    Segment(6.5, 3.0, "Never gonna give you up."),
)

PROVIDERS = [
    pytest.param("claude", ("ANTHROPIC_API_KEY",), "claude-opus-5", "anthropic", id="claude"),
    pytest.param("openai", ("OPENAI_API_KEY",), "gpt-5-mini", "openai", id="openai"),
    pytest.param(
        "gemini",
        ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "gemini-2.5-flash",
        "google.genai",
        id="gemini",
    ),
    pytest.param(
        "openrouter", ("OPENROUTER_API_KEY",), "openai/gpt-5-mini", "openai", id="openrouter"
    ),
]


def live_model(provider: str, keys: tuple[str, ...], default: str, module: str) -> str:
    """``"provider=model"`` for a live run, or skip when the key or the SDK is missing."""
    if not any(os.environ.get(key) for key in keys):
        pytest.skip(f"{' or '.join(keys)} is not set")
    pytest.importorskip(module)
    return f"{provider}={os.environ.get(f'UTMAX_LIVE_{provider.upper()}_MODEL', default)}"


@pytest.mark.parametrize(("provider", "keys", "default", "module"), PROVIDERS)
def test_every_cue_is_translated_with_its_timing_kept(
    provider: str, keys: tuple[str, ...], default: str, module: str
) -> None:
    model = live_model(provider, keys, default, module)
    translation = utmax.translate(SOURCE, "tr", model=model)
    assert [(cue.start, cue.duration) for cue in translation] == [
        (cue.start, cue.duration) for cue in SOURCE
    ]
    assert all(cue.text.strip() for cue in translation)
    assert translation.text != SOURCE.text
    assert (translation.language_code, translation.language) == ("tr", "Turkish")
    assert translation.translator == model
    assert translation.source is not None
    assert len(translation.source) == len(SOURCE)


def test_fetch_translate_and_save_bilingual_subtitles(tmp_path: Path) -> None:
    model = live_model("claude", ("ANTHROPIC_API_KEY",), "claude-opus-5", "anthropic")
    transcript = utmax.fetch("dQw4w9WgXcQ")
    translation = utmax.translate(transcript, "tr", model=model)
    assert translation.source is not None
    assert len(translation) == len(translation.source)
    combined = utmax.bilingual(transcript, translation)
    assert (combined.language_code, combined.language) == ("en+tr", "English + Turkish")
    for name in ("rick.en+tr.srt", "rick.en+tr.vtt", "rick.en+tr.json", "rick.en+tr.txt"):
        data = combined.save(tmp_path / name).read_bytes()
        assert b"\r\n" not in data
        assert "♪".encode() in data
