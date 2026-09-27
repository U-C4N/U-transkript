"""AI translation providers: the Translator base class and one adapter per provider SDK."""

from __future__ import annotations

from typing import Any

from utmax.adapters.providers.base import EngineOptions, SDKTranslator, Translator
from utmax.adapters.providers.claude import ClaudeTranslator
from utmax.adapters.providers.gemini import GeminiTranslator
from utmax.adapters.providers.openai import OpenAITranslator
from utmax.adapters.providers.openrouter import OpenRouterTranslator
from utmax.core.translate.spec import parse_model_spec
from utmax.errors import InvalidOption

__all__ = [
    "TRANSLATORS",
    "ClaudeTranslator",
    "EngineOptions",
    "GeminiTranslator",
    "OpenAITranslator",
    "OpenRouterTranslator",
    "Translator",
    "create_translator",
]

TRANSLATORS: dict[str, type[SDKTranslator]] = {
    "claude": ClaudeTranslator,
    "openai": OpenAITranslator,
    "gemini": GeminiTranslator,
    "openrouter": OpenRouterTranslator,
}


def create_translator(model: str, **options: Any) -> Translator:
    """The built-in translator for ``model`` (``"provider=model-id"``); see :func:`utmax.translator`."""
    spec = parse_model_spec(model)
    if "base_url" in options and spec.provider != "openai":
        raise InvalidOption(
            f"base_url only works with the openai provider, not {spec.provider}.",
            suggestion=(
                'Use "openai=<model-id>" with base_url=... for Ollama, LM Studio and other '
                "OpenAI-compatible servers."
            ),
        )
    return TRANSLATORS[spec.provider](spec.model, **options)
