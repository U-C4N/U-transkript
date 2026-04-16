from __future__ import annotations

import re

import requests

from .url_parser import build_youtube_channel_url

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)

_VIDEO_ID_PATTERNS = [
    re.compile(r'"videoId":"([a-zA-Z0-9_-]{11})"'),
    re.compile(r"/watch\?v=([a-zA-Z0-9_-]{11})"),
    re.compile(r'"watchEndpoint":\{"videoId":"([a-zA-Z0-9_-]{11})"'),
    re.compile(r"watch\?v=([a-zA-Z0-9_-]{11})"),
    re.compile(r'"url":"/watch\?v=([a-zA-Z0-9_-]{11})"'),
    re.compile(r'href="/watch\?v=([a-zA-Z0-9_-]{11})"'),
]


def _channel_url_variants(channel_url: str) -> list[str]:
    return [
        channel_url,
        channel_url.replace("/videos?sort=dd", "/uploads?sort=dd"),
        channel_url.replace("/videos?sort=dd", "?sort=dd"),
        channel_url.replace("@", "c/"),
        channel_url.replace("@", "channel/"),
    ]


def _extract_ids_from_html(html: str) -> list[str]:
    ids: list[str] = []
    for pattern in _VIDEO_ID_PATTERNS:
        ids.extend(pattern.findall(html))
    return ids


def _dedup_preserving_order(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for video_id in ids:
        if video_id not in seen:
            seen.add(video_id)
            unique.append(video_id)
    return unique


def _fetch_html(url: str) -> str | None:
    try:
        response = requests.get(url, headers={"User-Agent": _USER_AGENT})
        response.raise_for_status()
        return response.text
    except Exception:
        return None


def get_channel_video_ids(username: str, max_count: int = 10) -> list[str]:
    channel_url = build_youtube_channel_url(username)

    try:
        collected: list[str] = []
        for url in _channel_url_variants(channel_url):
            html = _fetch_html(url)
            if html is None:
                continue
            collected.extend(_extract_ids_from_html(html))

        unique_ids = _dedup_preserving_order(collected)

        if len(unique_ids) < max_count:
            fallback_url = channel_url.replace("/videos?sort=dd", "?sort=dd")
            html = _fetch_html(fallback_url)
            if html is not None:
                extra = _extract_ids_from_html(html)
                unique_ids = _dedup_preserving_order(unique_ids + extra)

        unique_ids = unique_ids[:max_count]

        if not unique_ids:
            raise ValueError(f"No videos found for username: {username}")

        return unique_ids

    except ValueError:
        raise
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to fetch channel page: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to extract video IDs: {e}")
