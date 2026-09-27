"""Last resort: read the InnerTube API key from the watch page, passing the EU consent wall."""

from __future__ import annotations

import re

from utmax.core.clients import DESKTOP_USER_AGENT
from utmax.errors import (
    FailedToCreateConsentCookie,
    IpBlocked,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)
from utmax.transport import HttpRequest, Transport

__all__ = ["extract_api_key", "fetch_api_key"]

_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
_API_KEY = re.compile(r'"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"')
_CONSENT_FORM = 'action="https://consent.youtube.com/s"'
_CONSENT_VALUE = re.compile(r'name="v" value="(.*?)"')
_HEADERS = {
    "User-Agent": DESKTOP_USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}


def fetch_api_key(transport: Transport, video_id: str) -> str:
    """Download the watch page (accepting cookies for this call only) and read the API key."""
    page = _watch_page(transport, video_id, cookie=None)
    if _CONSENT_FORM in page:
        match = _CONSENT_VALUE.search(page)
        if match is None:
            raise FailedToCreateConsentCookie(
                "Could not read YouTube's cookie-consent form.", video_id=video_id
            )
        page = _watch_page(transport, video_id, cookie=f"CONSENT=YES+{match.group(1)}")
        if _CONSENT_FORM in page:
            raise FailedToCreateConsentCookie(
                "YouTube kept asking for cookie consent.", video_id=video_id
            )
    return extract_api_key(page, video_id=video_id)


def extract_api_key(page: str, *, video_id: str) -> str:
    """The ``INNERTUBE_API_KEY`` embedded in a watch page."""
    match = _API_KEY.search(page)
    if match is not None:
        return match.group(1)
    if 'class="g-recaptcha"' in page:
        raise IpBlocked("YouTube answered with a CAPTCHA page.", video_id=video_id)
    raise YouTubeDataUnparsable(
        "Could not find the InnerTube API key on the watch page.", video_id=video_id
    )


def _watch_page(transport: Transport, video_id: str, *, cookie: str | None) -> str:
    headers = dict(_HEADERS)
    if cookie is not None:
        headers["Cookie"] = cookie
    response = transport.send(HttpRequest("GET", _WATCH_URL.format(video_id=video_id), headers))
    if response.status == 429:
        raise IpBlocked(
            "YouTube rate-limited the watch page request (HTTP 429).", video_id=video_id
        )
    if response.status != 200:
        raise YouTubeRequestFailed(
            f"The watch page answered HTTP {response.status}.",
            status_code=response.status,
            video_id=video_id,
        )
    return response.text
