"""xAI's Grok models, which speak the OpenAI API, through the official ``openai`` SDK."""

from __future__ import annotations

import os
from typing import Any, Unpack

from utmax.adapters.providers.base import EngineOptions
from utmax.adapters.providers.openai import OpenAITranslator
from utmax.errors import ProviderAuthError

__all__ = ["XAI_BASE_URL", "GrokTranslator"]

XAI_BASE_URL = "https://api.x.ai/v1"


class GrokTranslator(OpenAITranslator):
    """Translates with xAI's Grok models (``pip install "u-transcript-max[grok]"``).

    Requests go to xAI's OpenAI-compatible API with strict JSON Schema output; the JSON mode
    steps down like ``OpenAITranslator(json_mode="auto")``.

    Args:
        model: a Grok model id such as ``"grok-4.7"``.
        api_key: the xAI API key; by default ``XAI_API_KEY`` (``OPENAI_API_KEY`` is never
            used).
        effort: how long the model reasons, ``"low"``, ``"medium"``, ``"high"`` or
            ``"xhigh"``; omitted means the model's default (``"high"`` for grok-4.7, whose
            reasoning cannot be turned off). Lower is faster.
        client: a ready ``openai.OpenAI`` client pointed at xAI.
        **engine: engine options, see :class:`utmax.providers.Translator`.
    """

    PROVIDER = "grok"
    EXTRA = "grok"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        effort: str | None = None,
        client: Any = None,
        **engine: Unpack[EngineOptions],
    ) -> None:
        super().__init__(model, api_key=api_key, effort=effort, client=client, **engine)
        self._service = "xAI"

    def _make_client(self, api_key: str | None, base_url: str | None) -> Any:
        key = api_key or os.environ.get("XAI_API_KEY")
        if not key:
            raise ProviderAuthError(
                "No xAI API key was found for the grok translator.",
                provider=self.PROVIDER,
                suggestion="Pass api_key=... or set the XAI_API_KEY environment variable.",
            )
        return self._sdk.OpenAI(api_key=key, base_url=XAI_BASE_URL)
