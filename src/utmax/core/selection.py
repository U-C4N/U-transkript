"""Choose the right subtitle track: manual before auto-generated, in the user's language order."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from utmax.errors import NoTranscriptFound
from utmax.models import Track

__all__ = ["describe_track", "select_track"]


def select_track(
    tracks: Sequence[Track],
    languages: Sequence[str] | str | None = None,
    *,
    include_manual: bool = True,
    include_generated: bool = True,
) -> Track:
    """Pick one track from ``tracks``.

    With ``languages``, each code is tried in order: a manual track in exactly that code, then a
    manual track in the same base language (``de`` finds ``de-DE``), then the same two steps for
    auto-generated tracks. Without ``languages`` the spoken language (that of the auto-generated
    track) wins, manual first. YouTube's own translation is never used implicitly.

    Raises:
        NoTranscriptFound: nothing matches; the error lists every available track.
    """
    requested = [languages] if isinstance(languages, str) else list(languages or [])
    candidates = [
        track for track in tracks if (include_generated if track.is_generated else include_manual)
    ]
    if requested:
        for code in requested:
            exact = [track for track in candidates if track.language_code.lower() == code.lower()]
            related = [track for track in candidates if _base(track.language_code) == _base(code)]
            for pool in (
                [track for track in exact if not track.is_generated],
                [track for track in related if not track.is_generated],
                [track for track in exact if track.is_generated],
                [track for track in related if track.is_generated],
            ):
                if pool:
                    return pool[0]
        raise _not_found(tracks, requested)
    spoken = next((track.language_code for track in tracks if track.is_generated), None)
    if spoken is not None:
        manual = _in_language([track for track in candidates if not track.is_generated], spoken)
        if manual:
            return manual[0]
        automatic = [track for track in _in_language(candidates, spoken) if track.is_generated]
        if automatic:
            return automatic[0]
    match = _manual_first(candidates)
    if match is None:
        raise _not_found(tracks, [])
    return match


def describe_track(track: Track) -> str:
    """A short human-readable label such as ``"de-DE (German (Germany), manual)"``."""
    kind = "auto-generated" if track.is_generated else "manual"
    return f"{track.language_code} ({track.language}, {kind})"


def _in_language(tracks: Sequence[Track], code: str) -> list[Track]:
    exact = [track for track in tracks if track.language_code.lower() == code.lower()]
    return exact or [track for track in tracks if _base(track.language_code) == _base(code)]


def _manual_first(tracks: Iterable[Track]) -> Track | None:
    ordered = list(tracks)
    manual = next((track for track in ordered if not track.is_generated), None)
    return manual if manual is not None else next(iter(ordered), None)


def _base(code: str) -> str:
    return code.split("-", maxsplit=1)[0].lower()


def _not_found(tracks: Sequence[Track], requested: list[str]) -> NoTranscriptFound:
    video_id = tracks[0].video_id if tracks else None
    available = tuple(describe_track(track) for track in tracks)
    wanted = f"in {', '.join(requested)} " if requested else ""
    return NoTranscriptFound(
        f"No subtitles {wanted}match the filters for video {video_id}. "
        f"Available: {'; '.join(available) or 'none'}.",
        requested=tuple(requested),
        available=available,
        video_id=video_id,
    )
