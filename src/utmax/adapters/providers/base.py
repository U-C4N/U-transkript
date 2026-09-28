"""What every translator provides, plus the plumbing shared by the built-in providers."""

from __future__ import annotations

import importlib
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from types import ModuleType
from typing import Any, ClassVar, TypedDict, Unpack

from utmax.errors import (
    InvalidOption,
    ProviderAuthError,
    ProviderError,
    ProviderNotInstalled,
    ProviderRateLimited,
    TranslationError,
)

__all__ = [
    "EngineOptions",
    "SDKTranslator",
    "Translator",
    "positive_int",
    "redact_secrets",
    "stainless_error",
]

_SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9_*-]{6,}|AIza[0-9A-Za-z_-]{20,})")


class EngineOptions(TypedDict, total=False):
    """The engine options every translator accepts as keyword arguments."""

    batch_chars: int
    batch_items: int
    context_items: int
    concurrency: int
    max_attempts: int


def positive_int(option: str, value: object, *, minimum: int = 1) -> int:
    """``value`` when it is an integer of at least ``minimum``, else :class:`InvalidOption`."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise InvalidOption(f"{option} must be an integer of at least {minimum}, not {value!r}.")
    return value


def redact_secrets(text: str) -> str:
    """``text`` with anything shaped like an API key replaced by ``[redacted]``."""
    return _SECRET.sub("[redacted]", text)


class Translator(ABC):
    """Translates batches of subtitle cues by asking an AI model for JSON.

    Use :func:`utmax.translator` to get one of the built-in translators from a
    ``"provider=model-id"`` string, or subclass this to plug in any other model: implement
    :attr:`name` and :meth:`generate_json`, then pass an instance as ``model=`` to
    :func:`utmax.translate`.

    The engine options control how :func:`utmax.translate` splits the work:

    Args:
        batch_chars: most characters of cue text in one request.
        batch_items: most cues in one request.
        context_items: neighbouring source cues sent on each side as read-only context.
        concurrency: requests running at the same time.
        max_attempts: tries per batch before it is split in half.
    """

    def __init__(
        self,
        *,
        batch_chars: int = 4000,
        batch_items: int = 50,
        context_items: int = 3,
        concurrency: int = 4,
        max_attempts: int = 2,
    ) -> None:
        self.batch_chars = positive_int("batch_chars", batch_chars)
        self.batch_items = positive_int("batch_items", batch_items)
        self.context_items = positive_int("context_items", context_items, minimum=0)
        self.concurrency = positive_int("concurrency", concurrency)
        self.max_attempts = positive_int("max_attempts", max_attempts)

    @property
    @abstractmethod
    def name(self) -> str:
        """``"provider=model-id"``, for example ``"claude=claude-opus-5"``.

        Stored as ``Transcript.translator`` on every translation.
        """

    @property
    def provider(self) -> str:
        """The provider part of :attr:`name`, used in error reports."""
        return self.name.partition("=")[0]

    @abstractmethod
    def generate_json(self, system: str, prompt: str, schema: Mapping[str, Any]) -> str:
        """Send one request and return the model's raw answer, which should be JSON.

        Args:
            system: the system prompt.
            prompt: the user message, a JSON document describing one batch.
            schema: the JSON schema the answer must match.

        Raise :class:`utmax.providers.InvalidResponse` for an answer that cannot be used, such
        as one cut off by a token limit (the engine retries, then splits the batch), and a
        :class:`utmax.errors.TranslationError` subclass when the provider fails (never retried).
        """

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.name!r})"


class SDKTranslator(Translator):
    """Base of the built-in translators: a provider id, a model id and a lazily imported SDK.

    API keys are handed straight to the SDK client and never stored, logged or shown by utmax.
    """

    PROVIDER: ClassVar[str]
    EXTRA: ClassVar[str]

    def __init__(self, model: str, **engine: Unpack[EngineOptions]) -> None:
        super().__init__(**engine)
        if not isinstance(model, str) or not model.strip():
            raise InvalidOption(f"The {self.PROVIDER} model id must not be empty, got {model!r}.")
        self.model = model.strip()

    @property
    def name(self) -> str:
        return f"{self.PROVIDER}={self.model}"

    def import_sdk(self, module: str) -> ModuleType:
        """Import ``module`` (the provider's SDK), or say which extra installs it."""
        try:
            return importlib.import_module(module)
        except ImportError as error:
            command = f'pip install "u-transcript-max[{self.EXTRA}]"'
            raise ProviderNotInstalled(
                f"The {self.PROVIDER} translator needs the {module!r} package: {command}",
                provider=self.PROVIDER,
                extra=self.EXTRA,
                suggestion=f"Install the {self.EXTRA} extra with: {command}",
            ) from error


def stainless_error(
    sdk: Any, error: BaseException, *, provider: str, service: str
) -> TranslationError | None:
    """Map an exception of the Anthropic or OpenAI SDK (both generated by Stainless).

    ``service`` names the server in the message ("Anthropic", "the server at ..."). Returns
    ``None`` for exceptions that are not API failures, which callers re-raise.
    """
    detail = redact_secrets(str(getattr(error, "message", "") or error))
    status = getattr(error, "status_code", None)
    if isinstance(error, (sdk.AuthenticationError, sdk.PermissionDeniedError)):
        return ProviderAuthError(
            f"Credentials rejected by {service} (HTTP {status}): {detail}", provider=provider
        )
    if isinstance(error, sdk.RateLimitError):
        return ProviderRateLimited(
            f"Still rate-limited by {service} after the SDK's retries: {detail}",
            provider=provider,
        )
    if isinstance(error, sdk.APIStatusError):
        return ProviderError(
            f"HTTP {status} from {service}: {detail}", provider=provider, status_code=status
        )
    if isinstance(error, sdk.APIConnectionError):
        return ProviderError(f"Could not reach {service}: {detail}", provider=provider)
    return None
