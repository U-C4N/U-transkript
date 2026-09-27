"""OpenAI and OpenAI-compatible servers through the official ``openai`` SDK."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from typing import Any, Literal, Unpack

from utmax.adapters.http import redact
from utmax.adapters.providers.base import EngineOptions, SDKTranslator, stainless_error
from utmax.core.translate.batching import InvalidResponse
from utmax.errors import InvalidOption, ProviderAuthError, TranslationRefused

__all__ = ["JsonMode", "OpenAITranslator"]

log = logging.getLogger("utmax.translate")

JsonMode = Literal["auto", "json_schema", "json_object", "prompt"]

_MODES: tuple[JsonMode, ...] = ("auto", "json_schema", "json_object", "prompt")
_STEP_DOWN: dict[str, JsonMode] = {"json_schema": "json_object", "json_object": "prompt"}
_FORMAT_WORDS = ("response_format", "json_schema", "json_object", "structured output")
_SCHEMA_NAME = "subtitle_translation"
_NO_KEY = "not-needed"


class OpenAITranslator(SDKTranslator):
    """Translates with OpenAI or any OpenAI-compatible server (``pip install
    "u-transcript-max[openai]"``): Ollama, LM Studio, vLLM, Groq, DeepSeek and others.

    Args:
        model: a model id such as ``"gpt-5-mini"`` or ``"llama3.1:8b"``.
        api_key: the API key. Without ``base_url`` the SDK falls back to ``OPENAI_API_KEY``;
            with ``base_url`` only this argument is sent, so your OpenAI key never reaches
            another server and keyless local servers need nothing.
        base_url: the address of an OpenAI-compatible API, such as
            ``"http://localhost:11434/v1"`` for Ollama.
        json_mode: how the answer is kept to JSON: ``"json_schema"`` (strict structured
            output), ``"json_object"``, ``"prompt"`` (instructions only) or ``"auto"``, which
            starts with ``json_schema`` and steps down each time the server rejects the mode,
            remembering the working one for later requests.
        client: a ready ``openai.OpenAI`` client, used instead of creating one.
        **engine: engine options, see :class:`utmax.providers.Translator`.
    """

    PROVIDER = "openai"
    EXTRA = "openai"

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        json_mode: JsonMode = "auto",
        client: Any = None,
        **engine: Unpack[EngineOptions],
    ) -> None:
        super().__init__(model, **engine)
        if json_mode not in _MODES:
            raise InvalidOption(f"json_mode must be one of {', '.join(_MODES)}, not {json_mode!r}.")
        self.json_mode = json_mode
        self._mode: JsonMode = "json_schema" if json_mode == "auto" else json_mode
        self._lock = threading.Lock()
        self._extra_body: dict[str, Any] | None = None
        self._service = "OpenAI" if base_url is None else f"the server at {redact(base_url)}"
        self._sdk = self.import_sdk("openai")
        self._client = client if client is not None else self._make_client(api_key, base_url)

    @property
    def mode(self) -> JsonMode:
        """The JSON mode of the next request; ``"auto"`` settles on one of the other three."""
        return self._mode

    def generate_json(self, system: str, prompt: str, schema: Mapping[str, Any]) -> str:
        while True:
            mode = self._mode
            try:
                completion = self._client.chat.completions.create(
                    **self._request(mode, system, prompt, schema)
                )
            except self._sdk.OpenAIError as error:
                if self._rejects_json_mode(mode, error):
                    self._step_down(mode)
                    continue
                mapped = stainless_error(
                    self._sdk, error, provider=self.PROVIDER, service=self._service
                )
                if mapped is None:
                    raise
                raise mapped from error
            return self._answer(completion)

    def _make_client(self, api_key: str | None, base_url: str | None) -> Any:
        if base_url is not None and api_key is None:
            api_key = _NO_KEY
        try:
            return self._sdk.OpenAI(api_key=api_key, base_url=base_url)
        except self._sdk.OpenAIError as error:
            raise ProviderAuthError(
                "No OpenAI API key was found for the openai translator.",
                provider=self.PROVIDER,
                suggestion="Pass api_key=... or set the OPENAI_API_KEY environment variable.",
            ) from error

    def _request(
        self, mode: JsonMode, system: str, prompt: str, schema: Mapping[str, Any]
    ) -> dict[str, Any]:
        if mode != "json_schema":
            system += (
                "\n\nThe reply must be a JSON object that matches this JSON Schema:\n"
                + json.dumps(dict(schema))
            )
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        if mode == "json_schema":
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": _SCHEMA_NAME, "schema": dict(schema), "strict": True},
            }
        elif mode == "json_object":
            request["response_format"] = {"type": "json_object"}
        if self._extra_body is not None:
            request["extra_body"] = self._extra_body
        return request

    def _rejects_json_mode(self, mode: JsonMode, error: Exception) -> bool:
        if self.json_mode != "auto" or mode not in _STEP_DOWN:
            return False
        if not isinstance(error, (self._sdk.BadRequestError, self._sdk.UnprocessableEntityError)):
            return False
        text = f"{getattr(error, 'message', '')} {getattr(error, 'body', '')}".lower()
        return any(word in text for word in _FORMAT_WORDS)

    def _step_down(self, tried: JsonMode) -> None:
        with self._lock:
            if self._mode == tried:
                self._mode = _STEP_DOWN[tried]
                log.info(
                    "%s rejected response_format %s; using %s from now on",
                    self.name,
                    tried,
                    self._mode,
                )

    def _answer(self, completion: Any) -> str:
        if not completion.choices:
            raise InvalidResponse("the answer had no choices")
        choice = completion.choices[0]
        refusal = getattr(choice.message, "refusal", None)
        if refusal:
            raise TranslationRefused(
                f"The model declined to translate this batch: {refusal}", provider=self.PROVIDER
            )
        if choice.finish_reason == "content_filter":
            raise TranslationRefused(
                "The provider's content filter blocked this batch.", provider=self.PROVIDER
            )
        text: str = choice.message.content or ""
        if choice.finish_reason == "length":
            raise InvalidResponse("the answer was cut off (finish_reason=length)", raw=text)
        return text
