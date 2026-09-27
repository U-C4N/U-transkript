"""The translators behind :func:`utmax.translate`, for direct use or subclassing.

Pick one with :func:`utmax.translator` (``"provider=model-id"``) or build it yourself::

    from utmax.providers import ClaudeTranslator

    translator = ClaudeTranslator("claude-opus-5", effort="low", batch_items=20)
    tr = utmax.translate(transcript, "tr", model=translator)

To use any other model, subclass :class:`Translator` and implement ``name`` and
``generate_json``. Provider SDKs are imported only when a translator is created.
"""

from __future__ import annotations

from utmax.adapters.providers import (
    ClaudeTranslator,
    EngineOptions,
    GeminiTranslator,
    OpenAITranslator,
    OpenRouterTranslator,
    Translator,
)
from utmax.adapters.providers.openai import JsonMode
from utmax.core.translate.batching import InvalidResponse

__all__ = [
    "ClaudeTranslator",
    "EngineOptions",
    "GeminiTranslator",
    "InvalidResponse",
    "JsonMode",
    "OpenAITranslator",
    "OpenRouterTranslator",
    "Translator",
]
