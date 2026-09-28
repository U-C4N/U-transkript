"""Combine an original transcript and its translation into one two-language transcript."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence

from utmax.core.languages import english_name
from utmax.errors import InvalidOption
from utmax.models import Segment, Transcript

__all__ = ["bilingual"]


def bilingual(
    original: Transcript, translation: Transcript, *, translation_first: bool = False
) -> Transcript:
    """One transcript that shows ``original`` and ``translation`` together.

    AI translations remember the exact cues they were made from (``translation.source``); when
    those cues belong to ``original`` (same video, same language code and the same auto/manual
    kind, since a video's auto track and manual track can share a language code) the two are
    paired one to one. Otherwise, for example with YouTube's own translation, another track or
    the sibling auto/manual track in the same language, every translated cue joins the original
    cue that contains its midpoint (or the nearest one), so the timing always follows
    ``original``.

    Each cue reads ``original + "\\n" + translation`` (``translation_first=True`` swaps the
    two). The language code is ``"<original>+<translation>"`` such as ``"en+tr"`` and the name
    ``"English + Turkish"``, whatever the order of the lines.

    Raises:
        InvalidOption: one of the transcripts is already bilingual.
    """
    for transcript in (original, translation):
        if transcript.is_bilingual:
            raise InvalidOption(
                f"The {transcript.language_code} transcript is already bilingual; pass the "
                "original transcript and its translation instead.",
                video_id=transcript.video.video_id,
            )
    segments = tuple(
        Segment(
            start=cue.start,
            duration=cue.duration,
            text=_join(cue.text, text, translation_first=translation_first),
        )
        for cue, text in _pairs(original, translation)
    )
    return Transcript(
        video=original.video,
        language_code=f"{original.language_code}+{translation.language_code}",
        language=f"{_name(original)} + {_name(translation)}",
        is_generated=original.is_generated or translation.is_generated,
        segments=segments,
        translated_from=translation.translated_from,
        translator=translation.translator,
    )


def _pairs(original: Transcript, translation: Transcript) -> list[tuple[Segment, str]]:
    source = translation.source
    if (
        source is not None
        and len(source) == len(translation)
        and source.language_code == original.language_code
        and source.video.video_id == original.video.video_id
        and source.is_generated == original.is_generated
    ):
        return [
            (cue, translated.text)
            for cue, translated in zip(source.segments, translation.segments, strict=True)
        ]
    return _by_midpoint(original.segments, translation.segments)


def _by_midpoint(
    originals: Sequence[Segment], translated: Sequence[Segment]
) -> list[tuple[Segment, str]]:
    cues = sorted((cue for cue in originals if cue.text.strip()), key=lambda cue: cue.start)
    if not cues:
        return []
    starts = [cue.start for cue in cues]
    assigned: list[list[str]] = [[] for _ in cues]
    for segment in sorted(translated, key=lambda segment: segment.start):
        if not segment.text.strip():
            continue
        middle = segment.start + segment.duration / 2
        index = bisect_right(starts, middle) - 1
        if index < 0 or middle >= cues[index].end:
            index = min(
                (i for i in (index, index + 1) if 0 <= i < len(cues)),
                key=lambda i: abs(cues[i].start + cues[i].duration / 2 - middle),
            )
        assigned[index].append(segment.text.strip())
    return [(cue, " ".join(texts)) for cue, texts in zip(cues, assigned, strict=True)]


def _join(original: str, translated: str, *, translation_first: bool) -> str:
    parts = [original.strip(), translated.strip()]
    if translation_first:
        parts.reverse()
    return "\n".join(part for part in parts if part)


def _name(transcript: Transcript) -> str:
    return english_name(transcript.language_code) or transcript.language
