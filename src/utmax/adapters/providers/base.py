"""What every translator provides: engine options plus one JSON request to an AI model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from utmax.errors import InvalidOption

__all__ = ["Translator", "positive_int"]


def positive_int(option: str, value: object, *, minimum: int = 1) -> int:
    """``value`` when it is an integer of at least ``minimum``, else :class:`InvalidOption`."""
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise InvalidOption(f"{option} must be an integer of at least {minimum}, not {value!r}.")
    return value


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
