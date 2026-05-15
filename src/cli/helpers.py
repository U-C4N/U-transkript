from __future__ import annotations

from typing import Any, Iterable

EXIT_SUCCESS = 0
EXIT_USER_ERROR = 1
EXIT_NETWORK_ERROR = 2
EXIT_API_ERROR = 3


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
