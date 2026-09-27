"""Extract the 11-character video ID from anything a user might paste."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from utmax.errors import InvalidVideoId

__all__ = ["parse_video_id"]

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
    if not text:
        return None
    if text.startswith("//"):
        text = f"https:{text}"
    elif not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
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
