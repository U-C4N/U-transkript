"""The language-neutral protocol shared with the future browser extension.

The numbers live in ``data/protocol.json`` so another implementation (the TypeScript extension)
can load exactly the same values. M1 uses only the segmentation rules; M2 adds the translation
protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

__all__ = ["SegmentationRules", "segmentation_rules"]


@dataclass(frozen=True, slots=True)
class SegmentationRules:
    """Thresholds used by :func:`utmax.core.segmentation.merge_sentences`."""

    terminal_punctuation: str
    closing_characters: str
    max_gap_seconds: float
    max_duration_seconds: float
    max_characters: int


@cache
def _protocol() -> dict[str, Any]:
    text = (
        files("utmax.core.translate").joinpath("data", "protocol.json").read_text(encoding="utf-8")
    )
    data: dict[str, Any] = json.loads(text)
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
