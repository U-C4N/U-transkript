"""Find the video, playlist or channel in anything a user might paste."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import SplitResult, parse_qs, urlsplit

from utmax.errors import CollectionUnavailable, InvalidSource, InvalidVideoId
from utmax.models import CollectionKind

__all__ = [
    "COLLECTION_KINDS",
    "Source",
    "parse_source",
    "parse_video_id",
    "uploads_playlist_id",
]

COLLECTION_KINDS: tuple[CollectionKind, ...] = ("all", "videos", "shorts", "live")

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_WATCH_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)
_SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
_ID_PATH_PREFIXES = frozenset({"shorts", "live", "embed", "v", "e"})
_RESERVED_WORDS = frozenset({"videoseries", "live_stream"})
_PLAYLIST_ID = re.compile(r"(?:PL|UU|FL|OLAK5uy_)[A-Za-z0-9_-]{10,}")
_LIST_ID = re.compile(r"[A-Za-z0-9_-]+")
_MIX_ID = re.compile(r"RD[A-Za-z0-9_-]*")
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
_HANDLE = re.compile(r"@[^\s/?#]+")
_UPLOADS_PREFIXES: dict[CollectionKind, str] = {
    "all": "UU",
    "videos": "UULF",
    "shorts": "UUSH",
    "live": "UULV",
}
_TABS: dict[str, CollectionKind] = {"videos": "videos", "shorts": "shorts", "streams": "live"}


def parse_video_id(value: str) -> str:
    """Return the video ID in ``value``: a bare ID or any common YouTube URL.

    Raises:
        InvalidVideoId: if no video ID can be found. No network request is ever made.
    """
    text = value.strip()
    if _VIDEO_ID.fullmatch(text):
        return text
    candidate = _id_from_url(text)
    if candidate is None:
        raise InvalidVideoId(f"Could not find a YouTube video ID in {value!r}.")
    return candidate


def _id_from_url(text: str) -> str | None:
    parts = _split_url(text)
    if parts is None:
        return None
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]
    if host in _SHORT_HOSTS:
        candidate = segments[0] if segments else ""
    elif host in _WATCH_HOSTS:
        if len(segments) > 1 and segments[0].lower() in _ID_PATH_PREFIXES:
            candidate = segments[1]
        elif not segments or segments[0].lower() == "watch":
            candidate = parse_qs(parts.query).get("v", [""])[0]
        else:
            return None
    else:
        return None
    return (
        candidate if _VIDEO_ID.fullmatch(candidate) and candidate not in _RESERVED_WORDS else None
    )


@dataclass(frozen=True, slots=True)
class Source:
    """What :func:`parse_source` found: a playlist, or a channel.

    ``id`` is the playlist ID, or the channel ID when it was given; for channels given by
    handle or custom URL it is empty and ``url`` must be resolved to the channel ID first.
    ``tab`` is the list a channel link's tab shows (``/videos``, ``/shorts``, ``/streams``),
    or ``None``.
    """

    kind: Literal["playlist", "channel"]
    id: str = ""
    url: str = ""
    tab: CollectionKind | None = None


def parse_source(value: str) -> Source:
    """The playlist or channel in ``value``.

    Playlists: any YouTube URL with ``list=``, or a bare playlist ID (``PL``, ``UU``, ``FL`` or
    ``OLAK5uy_`` followed by at least 10 characters). Channels: ``/@handle``,
    ``/channel/UC...``, ``/c/name`` and ``/user/name`` URLs, a bare ``@handle``, or a bare
    channel ID (``UC`` followed by 22 characters). A channel URL's ``/videos``, ``/shorts`` or
    ``/streams`` tab becomes ``tab`` (``"videos"``, ``"shorts"``, ``"live"``); other tabs are
    ignored.

    Raises:
        CollectionUnavailable: ``value`` is a Mix or another playlist YouTube generates
            (``RD...``, including YouTube Music's ``RDCLAK5uy_...``), which utmax does not list.
        InvalidSource: ``value`` names no playlist or channel. No request is ever made.
    """
    text = value.strip()
    if _CHANNEL_ID.fullmatch(text):
        return Source("channel", id=text)
    if _HANDLE.fullmatch(text):
        return Source("channel", url=f"https://www.youtube.com/{text}")
    if _MIX_ID.fullmatch(text) and not _VIDEO_ID.fullmatch(text):
        raise _generated(value, text)
    if _PLAYLIST_ID.fullmatch(text):
        return Source("playlist", id=text)
    source = _source_from_url(text, value)
    if source is not None:
        return source
    try:
        parse_video_id(text)
    except InvalidVideoId:
        raise InvalidSource(f"Could not find a playlist or channel in {value!r}.") from None
    raise InvalidSource(
        f"{value!r} is a single video, not a playlist or a channel.",
        suggestion=(
            "Use utmax.fetch() or utmax.download() for one video, or pass the link of its "
            "playlist or channel."
        ),
    )


def uploads_playlist_id(channel_id: str, kind: CollectionKind) -> str:
    """The playlist YouTube keeps of a channel's uploads: all of them, long videos, Shorts or
    live streams (``UU``, ``UULF``, ``UUSH`` or ``UULV`` plus the channel ID without ``UC``)."""
    return f"{_UPLOADS_PREFIXES[kind]}{channel_id[2:]}"


def _source_from_url(text: str, value: str) -> Source | None:
    parts = _split_url(text)
    if parts is None:
        return None
    host = (parts.hostname or "").lower()
    if host not in _WATCH_HOSTS and host not in _SHORT_HOSTS:
        return None
    playlist = parse_qs(parts.query).get("list", [""])[0].strip()
    if playlist:
        if playlist.startswith("RD"):
            raise _generated(value, playlist)
        return Source("playlist", id=playlist) if _LIST_ID.fullmatch(playlist) else None
    segments = [segment for segment in parts.path.split("/") if segment]
    if host in _SHORT_HOSTS or not segments:
        return None
    first = segments[0]
    if _HANDLE.fullmatch(first):
        return Source("channel", url=f"https://www.youtube.com/{first}", tab=_tab(segments, 1))
    if len(segments) < 2:
        return None
    if first.lower() == "channel" and _CHANNEL_ID.fullmatch(segments[1]):
        return Source("channel", id=segments[1], tab=_tab(segments, 2))
    if first.lower() in ("c", "user"):
        url = f"https://www.youtube.com/{first.lower()}/{segments[1]}"
        return Source("channel", url=url, tab=_tab(segments, 2))
    return None


def _tab(segments: list[str], position: int) -> CollectionKind | None:
    """The list the channel tab at ``position`` of a URL path shows, if it names one."""
    return _TABS.get(segments[position].lower()) if len(segments) > position else None


def _split_url(text: str) -> SplitResult | None:
    if not text:
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    elif not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        return urlsplit(text)
    except ValueError:
        return None


def _generated(value: str, list_id: str) -> CollectionUnavailable:
    """The error for a playlist YouTube generates (``RD...``), which utmax does not list."""
    if list_id.startswith("RDCLAK5uy_"):
        return CollectionUnavailable(
            f"{value!r} is a YouTube Music playlist; utmax cannot list those yet.",
            source=value,
            reason="YouTube Music playlists (RDCLAK5uy_...) are not supported yet.",
            suggestion="List the artist's channel, or an album (OLAK5uy_...), instead.",
        )
    return CollectionUnavailable(
        f"{value!r} is a Mix, a playlist YouTube makes for each viewer; Mixes cannot be listed.",
        source=value,
        reason="YouTube does not list Mixes.",
    )
