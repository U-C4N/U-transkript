"""Cut transcripts into translation batches, build each request and check each answer.

Pure functions only: :mod:`utmax.services.translation` runs the batches in parallel and decides
when to retry a batch or split it in half.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from utmax.models import Language

__all__ = [
    "Batch",
    "InvalidResponse",
    "Item",
    "build_request",
    "make_batch",
    "parse_response",
    "plan_batches",
    "split_batch",
]


@dataclass(frozen=True, slots=True)
class Item:
    """One cue to translate; ``id`` is its position in the transcript."""

    id: int
    text: str


@dataclass(frozen=True, slots=True)
class Batch:
    """Consecutive items plus the neighbouring source lines sent as read-only context."""

    items: tuple[Item, ...]
    context_before: tuple[str, ...] = ()
    context_after: tuple[str, ...] = ()

    @property
    def ids(self) -> tuple[int, ...]:
        """The ids of :attr:`items`, in order."""
        return tuple(item.id for item in self.items)


class InvalidResponse(ValueError):
    """A model answer that cannot be used: bad JSON, wrong ids, empty texts or a cut-off reply.

    The engine retries the batch, then splits it in half. Translators raise it themselves when
    the provider reports a truncated reply.
    """

    def __init__(self, reason: str, *, raw: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.raw = raw


def make_batch(texts: Sequence[str], start: int, stop: int, *, context_items: int) -> Batch:
    """The batch of ``texts[start:stop]`` with up to ``context_items`` source lines each side."""
    return Batch(
        items=tuple(Item(index, texts[index]) for index in range(start, stop)),
        context_before=tuple(texts[max(0, start - context_items) : start]),
        context_after=tuple(texts[stop : stop + context_items]),
    )


def plan_batches(
    texts: Sequence[str], *, max_chars: int, max_items: int, context_items: int
) -> list[Batch]:
    """Group ``texts`` into consecutive batches of at most ``max_items`` items and ``max_chars``
    characters; a single text longer than ``max_chars`` gets a batch of its own."""
    batches: list[Batch] = []
    start = 0
    size = 0
    for index, text in enumerate(texts):
        count = index - start
        if count and (count >= max_items or size + len(text) > max_chars):
            batches.append(make_batch(texts, start, index, context_items=context_items))
            start, size = index, 0
        size += len(text)
    if start < len(texts):
        batches.append(make_batch(texts, start, len(texts), context_items=context_items))
    return batches


def split_batch(batch: Batch, texts: Sequence[str], *, context_items: int) -> tuple[Batch, Batch]:
    """The two halves of ``batch``, each with fresh context from ``texts``."""
    if len(batch.items) < 2:
        raise ValueError("Only a batch of two or more items can be split.")
    start = batch.items[0].id
    stop = batch.items[-1].id + 1
    middle = start + len(batch.items) // 2
    return (
        make_batch(texts, start, middle, context_items=context_items),
        make_batch(texts, middle, stop, context_items=context_items),
    )


def build_request(
    batch: Batch, *, source: Language, target: Language, instructions: str | None = None
) -> str:
    """The user message for ``batch``: a JSON document matching ``request.schema.json``."""
    payload = {
        "source_language": {"code": source.code, "name": source.name},
        "target_language": {"code": target.code, "name": target.name},
        "instructions": instructions,
        "context_before": list(batch.context_before),
        "items": [{"id": item.id, "text": item.text} for item in batch.items],
        "context_after": list(batch.context_after),
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_response(raw: str, ids: Sequence[int]) -> dict[int, str]:
    """Check a model answer and return ``{id: text}`` for exactly ``ids``.

    The JSON object may be wrapped in a Markdown code fence or a sentence of prose, as some
    OpenAI-compatible models reply that way. Texts are stripped; inner line breaks survive.

    Raises:
        InvalidResponse: the answer is not JSON, has the wrong shape, misses, repeats or adds
            ids, or contains an empty text.
    """
    try:
        data = json.loads(_object_text(raw))
    except ValueError:
        raise InvalidResponse("the answer is not valid JSON", raw=raw) from None
    entries = data.get("items") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise InvalidResponse('the answer has no "items" list', raw=raw)
    texts: dict[int, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise InvalidResponse("an item is not a JSON object", raw=raw)
        key, text = entry.get("id"), entry.get("text")
        if isinstance(key, bool) or not isinstance(key, int):
            raise InvalidResponse(f"item id {key!r} is not an integer", raw=raw)
        if not isinstance(text, str) or not text.strip():
            raise InvalidResponse(f"item {key} has an empty text", raw=raw)
        if key in texts:
            raise InvalidResponse(f"item {key} appears twice", raw=raw)
        texts[key] = text.strip()
    expected = set(ids)
    if set(texts) != expected:
        missing = sorted(expected - set(texts))
        unexpected = sorted(set(texts) - expected)
        raise InvalidResponse(f"wrong ids: missing {missing}, unexpected {unexpected}", raw=raw)
    return texts


def _object_text(raw: str) -> str:
    start, end = raw.find("{"), raw.rfind("}")
    return raw[start : end + 1] if 0 <= start < end else raw
