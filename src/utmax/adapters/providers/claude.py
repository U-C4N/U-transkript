"""Claude through the official ``anthropic`` SDK, with structured JSON output."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Unpack

from utmax.adapters.providers.base import (
    EngineOptions,
    SDKTranslator,
    positive_int,
    redact_secrets,
    stainless_error,
)
from utmax.core.translate.batching import InvalidResponse
from utmax.errors import InvalidOption, ProviderAuthError, TranslationRefused

__all__ = ["ClaudeTranslator"]

log = logging.getLogger("utmax.translate")

_EFFORTS = ("low", "medium", "high", "xhigh", "max")
_CUT_OFF = frozenset({"max_tokens", "model_context_window_exceeded"})


class ClaudeTranslator(SDKTranslator):
    """Translates with Anthropic's Claude models (``pip install "u-transcript-max[claude]"``).

    Args:
        model: a Claude model id such as ``"claude-opus-5"``.
        api_key: an Anthropic API key; by default the SDK finds one itself
            (``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN`` or an ``ant auth login`` profile).
        effort: ``"low"``, ``"medium"``, ``"high"``, ``"xhigh"`` or ``"max"``; omitted means
            the model's default.
        max_tokens: the most tokens one answer may use.
        client: a ready ``anthropic.Anthropic`` client, used instead of creating one.
        **engine: engine options, see :class:`utmax.providers.Translator`.
    """

    PROVIDER = "claude"
    EXTRA = "claude"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        effort: str | None = None,
        max_tokens: int = 16000,
        client: Any = None,
        **engine: Unpack[EngineOptions],
    ) -> None:
        super().__init__(model, **engine)
        if effort is not None and effort not in _EFFORTS:
            raise InvalidOption(f"effort must be one of {', '.join(_EFFORTS)}, not {effort!r}.")
        self.effort = effort
        self.max_tokens = positive_int("max_tokens", max_tokens)
        self._sdk = self.import_sdk("anthropic")
        if client is None:
            try:
                client = self._sdk.Anthropic(api_key=api_key)
            except self._sdk.CredentialsError as error:
                raise self._no_credentials(error) from error
        self._client = client

    def generate_json(self, system: str, prompt: str, schema: Mapping[str, Any]) -> str:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": dict(schema)}}
        if self.effort is not None:
            output_config["effort"] = self.effort
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config=output_config,
            )
        except TypeError as error:
            # anthropic raises this TypeError before sending when it finds no credentials.
            if "authentication" not in str(error).lower():
                raise
            raise self._no_credentials(error) from error
        except self._sdk.CredentialsError as error:
            raise self._no_credentials(error) from error
        except self._sdk.AnthropicError as error:
            mapped = stainless_error(self._sdk, error, provider=self.PROVIDER, service="Anthropic")
            if mapped is None:
                raise
            raise mapped from error
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None) or "unspecified"
            raise TranslationRefused(
                f"Claude declined to translate this batch (refusal category: {category}).",
                provider=self.PROVIDER,
            )
        text = "".join(block.text for block in message.content if block.type == "text")
        if message.stop_reason in _CUT_OFF:
            log.info("%s: the answer stopped early (%s)", self.name, message.stop_reason)
            raise InvalidResponse(f"the answer was cut off ({message.stop_reason})", raw=text)
        return text

    def _no_credentials(self, error: Exception) -> ProviderAuthError:
        return ProviderAuthError(
            f"No usable Anthropic credentials were found: {redact_secrets(str(error))}",
            provider=self.PROVIDER,
            suggestion="Pass api_key=... or set the ANTHROPIC_API_KEY environment variable.",
        )
