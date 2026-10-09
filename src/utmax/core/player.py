"""Parse InnerTube ``/player`` responses into typed data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from utmax.core.playability import Playability, parse_playability
from utmax.core.streams import Stream, parse_streams
from utmax.core.ytdata import items, mapping, text_of
from utmax.models import Language, VideoInfo

__all__ = ["CaptionTrackInfo", "PlayerData", "parse_player_response"]


@dataclass(frozen=True, slots=True)
class CaptionTrackInfo:
    """A caption track as listed in the player response."""

    base_url: str
    language_code: str
    name: str
    is_generated: bool
    is_translatable: bool
    vss_id: str


@dataclass(frozen=True, slots=True)
class PlayerData:
    """The parts of a player response utmax uses."""

    video: VideoInfo
    playability: Playability
    caption_tracks: tuple[CaptionTrackInfo, ...] | None
    translation_languages: tuple[Language, ...]
    streams: tuple[Stream, ...] = ()
    spoken_language: str | None = None


def parse_player_response(data: Mapping[str, Any], *, video_id: str) -> PlayerData:
    """Parse ``data``; missing or malformed parts become defaults instead of errors."""
    details = mapping(data.get("videoDetails"))
    video = VideoInfo(
        video_id=str(details.get("videoId") or video_id),
        title=str(details.get("title") or ""),
        channel=str(details.get("author") or ""),
        channel_id=str(details.get("channelId") or ""),
        duration=_seconds(details.get("lengthSeconds")),
        is_live_content=bool(details.get("isLiveContent", False)),
    )
    renderer = mapping(mapping(data.get("captions")).get("playerCaptionsTracklistRenderer"))
    tracks = tuple(
        _track(raw)
        for raw in map(mapping, items(renderer.get("captionTracks")))
        if isinstance(raw.get("baseUrl"), str)
    )
    languages = tuple(
        Language(
            code=str(raw["languageCode"]),
            name=text_of(raw.get("languageName")) or str(raw["languageCode"]),
        )
        for raw in map(mapping, items(renderer.get("translationLanguages")))
        if raw.get("languageCode")
    )
    streams = parse_streams(mapping(data.get("streamingData")))
    # Videos with dubbed audio mark their original track (videos with one track mark nothing).
    spoken = next((stream.format.language for stream in streams if stream.format.is_original), None)
    return PlayerData(
        video=video,
        playability=parse_playability(data),
        caption_tracks=tracks or None,
        translation_languages=languages if tracks else (),
        streams=streams,
        spoken_language=spoken,
    )


def _track(raw: Mapping[str, Any]) -> CaptionTrackInfo:
    code = str(raw.get("languageCode") or "")
    return CaptionTrackInfo(
        base_url=str(raw["baseUrl"]),
        language_code=code,
        name=text_of(raw.get("name")) or code,
        is_generated=raw.get("kind") == "asr",
        is_translatable=bool(raw.get("isTranslatable", False)),
        vss_id=str(raw.get("vssId") or ""),
    )


def _seconds(value: object) -> float:
    try:
        return float(str(value))
    except ValueError:
        return 0.0
