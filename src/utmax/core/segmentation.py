"""Merge fragmentary auto-generated captions into readable, sentence-sized cues."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from utmax.core.translate.protocol import SegmentationRules, segmentation_rules
from utmax.models import Segment, Word

__all__ = ["merge_sentences"]

_BRACKETED = re.compile(r"\[[^\]]*\]")


@dataclass(frozen=True, slots=True)
class _Unit:
    text: str
    start: float
    end: float
    words: tuple[Word, ...]


def merge_sentences(
    segments: Sequence[Segment], rules: SegmentationRules | None = None
) -> tuple[Segment, ...]:
    """Regroup ``segments`` into cues that end at sentence boundaries.

    Word timings are used when present (auto-generated tracks); otherwise whole segments are the
    units. A cue closes after sentence-ending punctuation, before a pause of at least
    ``max_gap_seconds``, or once it reaches ``max_duration_seconds`` or ``max_characters``.
    Bracketed sound tags such as ``[Music]`` always stand alone, and cues never overlap.
    """
    active = rules or segmentation_rules()
    units = _units(segments)
    groups: list[list[_Unit]] = []
    current: list[_Unit] = []
    for index, unit in enumerate(units):
        if _BRACKETED.fullmatch(unit.text):
            if current:
                groups.append(current)
                current = []
            groups.append([unit])
            continue
        current.append(unit)
        following = units[index + 1] if index + 1 < len(units) else None
        if _closes(current, following, active):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return tuple(_segment(group) for group in groups)


def _units(segments: Sequence[Segment]) -> list[_Unit]:
    provisional: list[_Unit] = []
    for segment in segments:
        if not segment.text.strip():
            continue
        words = [word for word in segment.words if word.text.strip()]
        if not words:
            text = " ".join(segment.text.split())
            provisional.append(_Unit(text, segment.start, segment.end, ()))
            continue
        for position, word in enumerate(words):
            end = words[position + 1].start if position + 1 < len(words) else segment.end
            text = word.text.strip()
            provisional.append(_Unit(text, word.start, end, (Word(text, word.start),)))
    provisional.sort(key=lambda unit: unit.start)
    units: list[_Unit] = []
    for index, unit in enumerate(provisional):
        end = unit.end
        if index + 1 < len(provisional):
            end = min(end, provisional[index + 1].start)
        units.append(_Unit(unit.text, unit.start, max(end, unit.start), unit.words))
    return units


def _closes(current: list[_Unit], following: _Unit | None, rules: SegmentationRules) -> bool:
    last = current[-1]
    if following is None or _ends_sentence(last.text, rules):
        return True
    return (
        following.start - last.end >= rules.max_gap_seconds
        or last.end - current[0].start >= rules.max_duration_seconds
        or len(" ".join(unit.text for unit in current)) >= rules.max_characters
    )


def _ends_sentence(text: str, rules: SegmentationRules) -> bool:
    body = text.rstrip(rules.closing_characters)
    return bool(body) and body[-1] in rules.terminal_punctuation


def _segment(group: list[_Unit]) -> Segment:
    start = group[0].start
    end = max(unit.end for unit in group)
    return Segment(
        start=start,
        duration=end - start,
        text=" ".join(unit.text for unit in group),
        words=tuple(word for unit in group for word in unit.words),
    )
