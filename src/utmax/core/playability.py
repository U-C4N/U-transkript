"""Map InnerTube's ``playabilityStatus`` to utmax errors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from utmax.core.ytdata import mapping, text_of, texts_of
from utmax.errors import AgeRestricted, RequestBlocked, VideoUnavailable, VideoUnplayable

__all__ = ["Playability", "check_playability", "parse_playability"]


@dataclass(frozen=True, slots=True)
class Playability:
    """What YouTube said about playing the video."""

    status: str
    reason: str = ""
    sub_reasons: tuple[str, ...] = ()


def parse_playability(player: Mapping[str, Any]) -> Playability:
    """Read ``playabilityStatus`` from a player response; a missing status means OK."""
    status = mapping(player.get("playabilityStatus"))
    renderer = mapping(mapping(status.get("errorScreen")).get("playerErrorMessageRenderer"))
    reason = status.get("reason")
    return Playability(
        status=str(status.get("status") or "OK"),
        reason=reason if isinstance(reason, str) and reason else text_of(renderer.get("reason")),
        sub_reasons=texts_of(renderer.get("subreason")),
    )


def check_playability(playability: Playability, *, video_id: str) -> None:
    """Raise the utmax error that matches a non-OK status (substring match, case-insensitive)."""
    status = playability.status.upper()
    if status == "OK":
        return
    reason = playability.reason.replace("\u2019", "'").lower()
    message = playability.reason or f"YouTube reported playability status {playability.status}."
    if status == "LOGIN_REQUIRED":
        if "not a bot" in reason:
            raise RequestBlocked(message, video_id=video_id)
        if "confirm your age" in reason or "inappropriate" in reason:
            raise AgeRestricted(message, video_id=video_id)
        raise VideoUnplayable(
            message,
            reason=playability.reason,
            sub_reasons=playability.sub_reasons,
            video_id=video_id,
            suggestion=(
                "This video needs a signed-in session (private or members-only), "
                "which utmax does not support."
            ),
        )
    if status == "ERROR" and "unavailable" in reason:
        raise VideoUnavailable(message, video_id=video_id)
    raise VideoUnplayable(
        message, reason=playability.reason, sub_reasons=playability.sub_reasons, video_id=video_id
    )
