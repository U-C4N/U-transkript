"""OpenRouter, which speaks the OpenAI API, through the official ``openai`` SDK."""

from __future__ import annotations

import os
from typing import Any, Unpack

from utmax.adapters.providers.base import EngineOptions
from utmax.adapters.providers.openai import OpenAITranslator
from utmax.errors import ProviderAuthError

__all__ = ["OPENROUTER_BASE_URL", "OpenRouterTranslator"]

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterTranslator(OpenAITranslator):
    """Translates with any model on OpenRouter (``pip install "u-transcript-max[openrouter]"``).

    Every request asks OpenRouter to route only to hosts that support all parameters sent
    (``provider.require_parameters``), so structured JSON output is honoured; the JSON mode
    steps down like ``OpenAITranslator(json_mode="auto")``.

    Args:
        model: an OpenRouter model id such as ``"anthropic/claude-opus-5"``.
        api_key: the OpenRouter key; by default ``OPENROUTER_API_KEY`` (``OPENAI_API_KEY`` is
            never used).
        app_name: your application's name, sent as OpenRouter's ``X-Title`` header.
        client: a ready ``openai.OpenAI`` client pointed at OpenRouter.
        **engine: engine options, see :class:`utmax.providers.Translator`.
    """

    PROVIDER = "openrouter"
    EXTRA = "openrouter"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        app_name: str | None = None,
        client: Any = None,
        **engine: Unpack[EngineOptions],
    ) -> None:
        self.app_name = app_name
        super().__init__(model, api_key=api_key, client=client, **engine)
        self._service = "OpenRouter"
        self._extra_body = {"provider": {"require_parameters": True}}

    def _make_client(self, api_key: str | None, base_url: str | None) -> Any:
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ProviderAuthError(
                "No OpenRouter API key was found for the openrouter translator.",
                provider=self.PROVIDER,
                suggestion="Pass api_key=... or set the OPENROUTER_API_KEY environment variable.",
            )
        headers = {"X-Title": self.app_name} if self.app_name else None
        return self._sdk.OpenAI(api_key=key, base_url=OPENROUTER_BASE_URL, default_headers=headers)
