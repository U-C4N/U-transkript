"""Read InnerTube ``browse`` and ``navigation/resolve_url`` answers about playlists and channels.

ANDROID_VR pages list ``playlistVideoRenderer`` items (20 a page) and continue through
``nextContinuationData``. WEB pages list ``lockupViewModel`` items (100 a page), or Shorts as
``richItemRenderer``/``shortsLockupViewModel``, and continue through a
``continuationItemViewModel`` (older pages: ``continuationItemRenderer``). WEB shows regular
playlists under a ``pageHeaderRenderer`` and channel upload lists under a
``playlistHeaderRenderer``, as ANDROID_VR does for both.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from utmax.core.ytdata import items, mapping, text_of
from utmax.errors import CollectionNotFound, CollectionUnavailable
from utmax.models import VideoEntry

__all__ = ["BrowsePage", "alert_error", "parse_browse_page", "resolved_channel_id"]

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_VIDEO_COUNT = re.compile(r"(\d[\d,]*) videos?")
_CLOCK = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})")
_LISTING_ROOTS = ("contents", "continuationContents", "onResponseReceivedActions")
_TOKEN_PATHS: dict[str, tuple[str, ...]] = {
    "nextContinuationData": ("continuation",),
    "continuationItemViewModel": (
        "continuationCommand",
        "innertubeCommand",
        "continuationCommand",
        "token",
    ),
    "continuationItemRenderer": ("continuationEndpoint", "continuationCommand", "token"),
}


@dataclass(frozen=True, slots=True)
class BrowsePage:
    """One ``browse`` answer.

    ``videos`` are the playable videos on the page, numbered 0 (a listing numbers them);
    ``items`` counts every list item, skipped ones included; ``continuation`` is the token of
    the next page. ``title``, ``video_count`` and the playlist's owner (``owner_name`` and
    ``owner_id``, the channel that owns it) come from the playlist header of a first page;
    continuation pages have no header, so a listing takes the owner from its first page.
    ``alerts`` are YouTube's messages, such as "The playlist does not exist.".
    """

    videos: tuple[VideoEntry, ...] = ()
    items: int = 0
    continuation: str | None = None
    title: str = ""
    video_count: int | None = None
    alerts: tuple[str, ...] = ()
    owner_name: str = ""
    owner_id: str = ""


def parse_browse_page(data: Mapping[str, Any]) -> BrowsePage:
    """Read a first or continuation page of either client; unknown parts are ignored."""
    title, video_count, owner = _header(data)
    listing = _Listing(owner)
    for root in _LISTING_ROOTS:
        listing.walk(data.get(root))
    return BrowsePage(
        videos=tuple(listing.videos),
        items=listing.items,
        continuation=listing.continuation,
        title=title,
        video_count=video_count,
        alerts=_alerts(data),
        owner_name=owner.name,
        owner_id=owner.channel_id,
    )


def resolved_channel_id(data: Mapping[str, Any]) -> str | None:
    """The channel a ``navigation/resolve_url`` answer points to; ``None`` when it points
    nowhere (ANDROID_VR answers an unknown handle with a plain ``urlEndpoint``)."""
    browse_id = _dig(data, "endpoint", "browseEndpoint", "browseId")
    return browse_id if isinstance(browse_id, str) and _CHANNEL_ID.fullmatch(browse_id) else None


def alert_error(page: BrowsePage, *, source: str) -> CollectionNotFound | CollectionUnavailable:
    """The error for a page that holds only alerts, such as WEB's answers for a missing
    playlist ("The playlist does not exist.") or a Mix ("This playlist type is unviewable.")."""
    reason = " ".join(page.alerts)
    if "does not exist" in reason.lower():
        return CollectionNotFound(f"YouTube cannot find {source!r}: {reason}", source=source)
    return CollectionUnavailable(
        f"YouTube will not list {source!r}: {reason}", source=source, reason=reason
    )


@dataclass(frozen=True, slots=True)
class _Owner:
    """The playlist's channel: the fallback for items that do not name theirs."""

    name: str = ""
    channel_id: str = ""


class _Listing:
    """Collects the videos and the first continuation token under a listing root."""

    def __init__(self, owner: _Owner) -> None:
        self.owner = owner
        self.videos: list[VideoEntry] = []
        self.items = 0
        self.continuation: str | None = None

    def walk(self, node: object) -> None:
        if isinstance(node, list):
            for child in node:
                self.walk(child)
            return
        if not isinstance(node, Mapping):
            return
        for key, value in node.items():
            reader = _ITEM_READERS.get(key)
            if reader is not None:
                self.items += 1
                entry = reader(mapping(value), self.owner)
                if entry is not None:
                    self.videos.append(entry)
            elif key in _TOKEN_PATHS:
                token = _dig(value, *_TOKEN_PATHS[key])
                if isinstance(token, str) and token and self.continuation is None:
                    self.continuation = token
            else:
                self.walk(value)


def _android_vr_video(raw: Mapping[str, Any], owner: _Owner) -> VideoEntry | None:
    video_id = _video_id(raw.get("videoId"))
    if video_id is None or raw.get("isPlayable") is False:
        return None
    byline = mapping(raw.get("shortBylineText"))
    return VideoEntry(
        video_id=video_id,
        title=text_of(raw.get("title")),
        duration=_seconds(raw.get("lengthSeconds")),
        channel=text_of(byline) or owner.name,
        channel_id=_run_channel_id(byline) or owner.channel_id,
        index=0,
    )


def _lockup_video(raw: Mapping[str, Any], owner: _Owner) -> VideoEntry | None:
    video_id = _video_id(raw.get("contentId"))
    if video_id is None:
        return None
    meta = mapping(_dig(raw, "metadata", "lockupMetadataViewModel"))
    name, channel_id = _lockup_channel(meta)
    return VideoEntry(
        video_id=video_id,
        title=str(_dig(meta, "title", "content") or ""),
        duration=_badge_seconds(raw),
        channel=name or owner.name,
        channel_id=channel_id or owner.channel_id,
        index=0,
    )


def _short_video(raw: Mapping[str, Any], owner: _Owner) -> VideoEntry | None:
    video_id = _video_id(_dig(raw, "onTap", "innertubeCommand", "reelWatchEndpoint", "videoId"))
    if video_id is None:
        return None
    return VideoEntry(
        video_id=video_id,
        title=str(_dig(raw, "overlayMetadata", "primaryText", "content") or ""),
        duration=None,
        channel=owner.name,
        channel_id=owner.channel_id,
        index=0,
    )


_ITEM_READERS: dict[str, Callable[[Mapping[str, Any], _Owner], VideoEntry | None]] = {
    "playlistVideoRenderer": _android_vr_video,
    "lockupViewModel": _lockup_video,
    "shortsLockupViewModel": _short_video,
}


def _header(data: Mapping[str, Any]) -> tuple[str, int | None, _Owner]:
    header = mapping(data.get("header"))
    classic = mapping(header.get("playlistHeaderRenderer"))
    if classic:
        owner_text = mapping(classic.get("ownerText"))
        title = text_of(classic.get("title"))
        video_count = _video_count(text_of(classic.get("numVideosText")))
        owner = _Owner(text_of(owner_text), _run_channel_id(owner_text))
    else:
        page = mapping(header.get("pageHeaderRenderer"))
        title = str(page.get("pageTitle") or "")
        counts = (_video_count(text) for text in _page_header_texts(page))
        video_count = next((count for count in counts if count is not None), None)
        owner = _Owner()
    title = title or str(_dig(data, "metadata", "playlistMetadataRenderer", "title") or "")
    return title, video_count, owner


def _page_header_texts(page: Mapping[str, Any]) -> list[str]:
    rows = items(
        _dig(
            page,
            "content",
            "pageHeaderViewModel",
            "metadata",
            "contentMetadataViewModel",
            "metadataRows",
        )
    )
    return [
        str(_dig(part, "text", "content") or "")
        for row in map(mapping, rows)
        for part in map(mapping, items(row.get("metadataParts")))
    ]


def _alerts(data: Mapping[str, Any]) -> tuple[str, ...]:
    texts: list[str] = []
    for alert in map(mapping, items(data.get("alerts"))):
        for renderer in ("alertRenderer", "alertWithButtonRenderer"):
            text = text_of(_dig(alert, renderer, "text")).strip()
            if text:
                texts.append(text)
    return tuple(texts)


def _lockup_channel(meta: Mapping[str, Any]) -> tuple[str, str]:
    """The first metadata text that links to a channel: that text and the channel ID."""
    rows = items(_dig(meta, "metadata", "contentMetadataViewModel", "metadataRows"))
    for row in map(mapping, rows):
        for part in map(mapping, items(row.get("metadataParts"))):
            text = mapping(part.get("text"))
            for command in map(mapping, items(text.get("commandRuns"))):
                browse_id = _dig(command, "onTap", "innertubeCommand", "browseEndpoint", "browseId")
                if isinstance(browse_id, str) and _CHANNEL_ID.fullmatch(browse_id):
                    return str(text.get("content") or ""), browse_id
    return "", ""


def _run_channel_id(text: Mapping[str, Any]) -> str:
    """The channel the runs of a text object link to, or ``""``."""
    for run in map(mapping, items(text.get("runs"))):
        browse_id = _dig(run, "navigationEndpoint", "browseEndpoint", "browseId")
        if isinstance(browse_id, str) and _CHANNEL_ID.fullmatch(browse_id):
            return browse_id
    return ""


def _badge_seconds(raw: Mapping[str, Any]) -> float | None:
    """The duration shown on a lockup's thumbnail ("3:51"); ``None`` for "LIVE" and the like."""
    for overlay in map(mapping, items(_dig(raw, "contentImage", "thumbnailViewModel", "overlays"))):
        for badge in map(
            mapping, items(_dig(overlay, "thumbnailBottomOverlayViewModel", "badges"))
        ):
            seconds = _clock_seconds(_dig(badge, "thumbnailBadgeViewModel", "text"))
            if seconds is not None:
                return seconds
    return None


def _clock_seconds(text: object) -> float | None:
    """``"3:51"`` is 231 seconds and ``"1:02:03"`` 3723; other text is ``None``."""
    match = _CLOCK.fullmatch(text.strip()) if isinstance(text, str) else None
    if match is None:
        return None
    hours, minutes, seconds = (int(group or 0) for group in match.groups())
    return float(hours * 3600 + minutes * 60 + seconds)


def _video_count(text: str) -> int | None:
    """``"139 videos"`` is 139, ``"1 video"`` 1 and ``"No videos"`` 0; other text is ``None``."""
    text = text.strip()
    if text.lower() == "no videos":
        return 0
    match = _VIDEO_COUNT.fullmatch(text)
    return int(match.group(1).replace(",", "")) if match else None


def _seconds(value: object) -> float | None:
    text = str(value) if isinstance(value, (str, int)) else ""
    # isdecimal, not isdigit: float() rejects the superscript digits that isdigit accepts.
    return float(text) if text.isdecimal() else None


def _video_id(value: object) -> str | None:
    return value if isinstance(value, str) and _VIDEO_ID.fullmatch(value) else None


def _dig(value: object, *keys: str) -> Any:
    """The value at ``keys`` inside nested JSON objects, or ``None``."""
    for key in keys:
        value = mapping(value).get(key)
    return value
