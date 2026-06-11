from __future__ import annotations

from typing import Any, Iterable

from utils.cache import TranscriptCache

EXIT_SUCCESS = 0
EXIT_USER_ERROR = 1
EXIT_NETWORK_ERROR = 2
EXIT_API_ERROR = 3


def fetch_transcript_cached(
    api, video_id: str, languages: list[str] | None = None, use_cache: bool = True
) -> list[dict]:
    """Fetch a transcript through the 24h disk cache (CLI paths only).

    The cache is an optimization and fails open: any cache I/O error falls
    back to a direct fetch instead of aborting the run.
    """
    language_key = ",".join(languages) if languages else "default"

    cache = None
    if use_cache:
        try:
            cache = TranscriptCache()
        except OSError:
            cache = None

    if cache is not None:
        try:
            cached = cache.get(video_id, language_key)
        except Exception:
            cached = None
        if cached is not None:
            return cached

    transcript = api.get_transcript(video_id, languages=languages)
    if cache is not None:
        try:
            cache.set(video_id, transcript, language_key)
        except OSError:
            pass
    return transcript


def build_formatter_kwargs(format_name: str) -> dict[str, Any]:
    if format_name == "pretty":
        return {"show_timestamps": True, "max_chars_per_line": 80}
    if format_name == "json":
        return {"indent": 2, "ensure_ascii": False}
    if format_name == "text":
        return {"separator": " "}
    return {}


def build_proxies(proxy_url: str | None) -> dict[str, str] | None:
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def get_progress_bar(
    iterable: Iterable, total: int | None = None, desc: str = ""
) -> Iterable:
    try:
        from tqdm import tqdm

        return tqdm(iterable, total=total, desc=desc, unit="video")
    except ImportError:
        return iterable
