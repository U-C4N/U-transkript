from __future__ import annotations

import re

_VIDEO_ID_PATTERNS = [
    re.compile(
        r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})"
    ),
    re.compile(r"^([a-zA-Z0-9_-]{11})$"),
]


def extract_video_id(url_or_id: str) -> str:
    for pattern in _VIDEO_ID_PATTERNS:
        match = pattern.search(url_or_id)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def build_youtube_channel_url(username: str) -> str:
    username = username.strip()

    if username.startswith("http"):
        return username

    if username.startswith("UC") and len(username) == 24:
        return f"https://www.youtube.com/channel/{username}/videos?sort=dd"

    if username.startswith("@"):
        username = username[1:]

    return f"https://www.youtube.com/@{username}/videos?sort=dd"
