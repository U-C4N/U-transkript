"""Only the optional provider extras add dependencies; the core stays dependency-free."""

from __future__ import annotations

from importlib.metadata import metadata

EXPECTED_REQUIREMENTS = {
    "anthropic<2,>=1.8; extra == 'ai'",
    "google-genai<3,>=2.25; extra == 'ai'",
    "openai<4,>=3.19; extra == 'ai'",
    "anthropic<2,>=1.8; extra == 'claude'",
    "google-genai<3,>=2.25; extra == 'gemini'",
    "openai<4,>=3.19; extra == 'openai'",
    "openai<4,>=3.19; extra == 'openrouter'",
}


def test_the_provider_extras_are_declared() -> None:
    extras = metadata("u-transcript-max").get_all("Provides-Extra") or []
    assert sorted(extras) == ["ai", "claude", "gemini", "openai", "openrouter"]


def test_every_requirement_belongs_to_an_extra() -> None:
    requirements = metadata("u-transcript-max").get_all("Requires-Dist") or []
    assert set(requirements) == EXPECTED_REQUIREMENTS
