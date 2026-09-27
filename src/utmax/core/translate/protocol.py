"""The language-neutral protocol shared with the future browser extension.

Everything lives in ``data/`` so another implementation (the TypeScript extension) can load
exactly the same values: ``protocol.json`` (segmentation and translation numbers),
``system_prompt.txt``, ``request.schema.json`` (the user message sent for every batch) and
``response.schema.json`` (the strict schema every answer must match).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

__all__ = [
    "SegmentationRules",
    "TranslationRules",
    "request_schema",
    "response_schema",
    "segmentation_rules",
    "system_prompt",
    "translation_rules",
]


@dataclass(frozen=True, slots=True)
class SegmentationRules:
    """Thresholds used by :func:`utmax.core.segmentation.merge_sentences`."""

    terminal_punctuation: str
    closing_characters: str
    max_gap_seconds: float
    max_duration_seconds: float
    max_characters: int


@dataclass(frozen=True, slots=True)
class TranslationRules:
    """Default engine options of every :class:`utmax.providers.Translator`."""

    batch_chars: int
    batch_items: int
    context_items: int
    concurrency: int
    max_attempts: int


@cache
def _data(name: str) -> str:
    return files("utmax.core.translate").joinpath("data", name).read_text(encoding="utf-8")


@cache
def _protocol() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_data("protocol.json"))
    return data


@cache
def segmentation_rules() -> SegmentationRules:
    """The default segmentation thresholds from ``protocol.json``."""
    raw = _protocol()["segmentation"]
    return SegmentationRules(
        terminal_punctuation=str(raw["terminal_punctuation"]),
        closing_characters=str(raw["closing_characters"]),
        max_gap_seconds=float(raw["max_gap_seconds"]),
        max_duration_seconds=float(raw["max_duration_seconds"]),
        max_characters=int(raw["max_characters"]),
    )


@cache
def translation_rules() -> TranslationRules:
    """The default translation engine options from ``protocol.json``."""
    raw = _protocol()["translation"]
    return TranslationRules(
        batch_chars=int(raw["batch_chars"]),
        batch_items=int(raw["batch_items"]),
        context_items=int(raw["context_items"]),
        concurrency=int(raw["concurrency"]),
        max_attempts=int(raw["max_attempts"]),
    )


def system_prompt() -> str:
    """The system prompt sent with every translation request."""
    return _data("system_prompt.txt").strip()


def request_schema() -> dict[str, Any]:
    """A fresh copy of the JSON schema of the user message sent for every batch."""
    schema: dict[str, Any] = json.loads(_data("request.schema.json"))
    return schema


def response_schema() -> dict[str, Any]:
    """A fresh copy of the strict JSON schema every answer must match."""
    schema: dict[str, Any] = json.loads(_data("response.schema.json"))
    return schema
