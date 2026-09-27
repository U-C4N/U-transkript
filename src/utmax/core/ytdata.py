"""Defensive readers for YouTube's loosely structured JSON."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["items", "mapping", "text_of", "texts_of"]


def mapping(value: object) -> Mapping[str, Any]:
    """``value`` if it is a JSON object, else an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def items(value: object) -> list[Any]:
    """``value`` if it is a JSON array, else an empty list."""
    return value if isinstance(value, list) else []


def text_of(value: object) -> str:
    """Read a YouTube text object: ``{"simpleText": ...}`` or ``{"runs": [{"text": ...}]}``."""
    simple = mapping(value).get("simpleText")
    if isinstance(simple, str):
        return simple
    return "".join(texts_of(value))


def texts_of(value: object) -> tuple[str, ...]:
    """The non-empty ``runs[].text`` strings of a YouTube text object."""
    runs = (mapping(run).get("text") for run in items(mapping(value).get("runs")))
    return tuple(text for text in runs if isinstance(text, str) and text)
