"""Gemini through the official ``google-genai`` SDK, with JSON Schema output."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Unpack

from utmax.adapters.providers.base import (
    EngineOptions,
    SDKTranslator,
    positive_int,
    redact_secrets,
)
from utmax.core.translate.batching import InvalidResponse
from utmax.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimited,
    TranslationError,
    TranslationRefused,
)

__all__ = ["GeminiTranslator"]

log = logging.getLogger("utmax.translate")

_REFUSED = frozenset(
    {"SAFETY", "RECITATION", "LANGUAGE", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}
)


class GeminiTranslator(SDKTranslator):
    """Translates with Google's Gemini models (``pip install "u-transcript-max[gemini]"``).

    Args:
        model: a Gemini model id such as ``"gemini-2.5-flash"``.
        api_key: a Gemini API key; by default the SDK reads ``GEMINI_API_KEY`` or
            ``GOOGLE_API_KEY``.
        retry_attempts: tries per request, the first included, on HTTP 408, 429 and 5xx; the
            SDK does not retry unless asked to.
        client: a ready ``google.genai.Client``, used instead of creating one.
        **engine: engine options, see :class:`utmax.providers.Translator`.
    """

    PROVIDER = "gemini"
    EXTRA = "gemini"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        retry_attempts: int = 5,
        client: Any = None,
        **engine: Unpack[EngineOptions],
    ) -> None:
        super().__init__(model, **engine)
        self.retry_attempts = positive_int("retry_attempts", retry_attempts)
        self._genai = self.import_sdk("google.genai")
        self._types = self.import_sdk("google.genai.types")
        self._errors = self.import_sdk("google.genai.errors")
        self._httpx = self.import_sdk("httpx")
        if client is None:
            try:
                client = self._genai.Client(api_key=api_key)
            except ValueError as error:
                raise ProviderAuthError(
                    f"No Gemini API key was found: {redact_secrets(str(error))}",
                    provider=self.PROVIDER,
                    suggestion="Pass api_key=... or set the GEMINI_API_KEY environment variable.",
                ) from error
        self._client = client

    def generate_json(self, system: str, prompt: str, schema: Mapping[str, Any]) -> str:
        types = self._types
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=dict(schema),
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=self.retry_attempts)
            ),
            # No tools are sent; this skips the SDK's function-calling loop and its log notice.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = self._client.models.generate_content(
                model=self.model, contents=prompt, config=config
            )
        except self._errors.APIError as error:
            raise self._api_error(error) from error
        except self._httpx.TransportError as error:
            raise ProviderError(
                f"Could not reach Gemini: {redact_secrets(str(error))}", provider=self.PROVIDER
            ) from error
        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason:
            raise TranslationRefused(
                f"Gemini blocked this batch ({_label(feedback.block_reason)}).",
                provider=self.PROVIDER,
            )
        candidate = response.candidates[0] if response.candidates else None
        reason = _label(candidate.finish_reason) if candidate is not None else ""
        if reason in _REFUSED:
            raise TranslationRefused(
                f"Gemini stopped answering this batch ({reason}).", provider=self.PROVIDER
            )
        text: str = response.text or ""
        if reason == "MAX_TOKENS":
            log.info("%s: the answer stopped early (MAX_TOKENS)", self.name)
            raise InvalidResponse("the answer was cut off (MAX_TOKENS)", raw=text)
        return text

    def _api_error(self, error: Any) -> TranslationError:
        code = error.code
        detail = redact_secrets(f"{error.status}: {error.message}")
        if code in (401, 403) or "api key" in str(error.message or "").lower():
            return ProviderAuthError(
                f"Credentials rejected by Gemini (HTTP {code}): {detail}", provider=self.PROVIDER
            )
        if code == 429:
            return ProviderRateLimited(
                f"Still rate-limited by Gemini after {self.retry_attempts} attempts: {detail}",
                provider=self.PROVIDER,
            )
        return ProviderError(
            f"HTTP {code} from Gemini: {detail}", provider=self.PROVIDER, status_code=code
        )


def _label(value: object) -> str:
    return str(getattr(value, "value", value) or "")
