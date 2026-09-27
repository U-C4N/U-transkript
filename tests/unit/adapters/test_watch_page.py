"""Tests for the watch-page fallback."""

from __future__ import annotations

import pytest

from tests.helpers.fake_transport import FakeTransport, text_response
from tests.helpers.youtube import VIDEO_ID
from utmax.adapters.watch_page import extract_api_key, fetch_api_key
from utmax.errors import (
    FailedToCreateConsentCookie,
    IpBlocked,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)

WATCH_HTML = '<script>ytcfg.set({"INNERTUBE_API_KEY": "AIzaTestKey_123-abc"});</script>'
CONSENT_HTML = (
    '<form action="https://consent.youtube.com/s" method="POST">'
    '<input type="hidden" name="v" value="cb.20260927-00-p0.en+FX+123"></form>'
)


def test_extract_api_key() -> None:
    assert extract_api_key(WATCH_HTML, video_id=VIDEO_ID) == "AIzaTestKey_123-abc"


def test_a_captcha_means_this_ip_is_blocked() -> None:
    with pytest.raises(IpBlocked):
        extract_api_key('<div class="g-recaptcha" data-sitekey="x"></div>', video_id=VIDEO_ID)


def test_a_page_without_the_key_is_unparsable() -> None:
    with pytest.raises(YouTubeDataUnparsable):
        extract_api_key("<html></html>", video_id=VIDEO_ID)


def test_the_consent_cookie_is_sent_on_the_second_request() -> None:
    transport = FakeTransport()
    transport.add("GET", "/watch?v=", text_response(CONSENT_HTML), text_response(WATCH_HTML))
    assert fetch_api_key(transport, VIDEO_ID) == "AIzaTestKey_123-abc"
    first, second = transport.requests
    assert first.url == f"https://www.youtube.com/watch?v={VIDEO_ID}"
    assert "Cookie" not in first.headers
    assert second.headers["Cookie"] == "CONSENT=YES+cb.20260927-00-p0.en+FX+123"


@pytest.mark.parametrize(
    "pages",
    [
        (CONSENT_HTML, CONSENT_HTML),
        ('<form action="https://consent.youtube.com/s"></form>',),
    ],
)
def test_a_consent_wall_that_cannot_be_passed(pages: tuple[str, ...]) -> None:
    transport = FakeTransport()
    transport.add("GET", "/watch?v=", *(text_response(page) for page in pages))
    with pytest.raises(FailedToCreateConsentCookie):
        fetch_api_key(transport, VIDEO_ID)


@pytest.mark.parametrize(("status", "error"), [(429, IpBlocked), (500, YouTubeRequestFailed)])
def test_watch_page_http_errors(status: int, error: type[Exception]) -> None:
    transport = FakeTransport()
    transport.add("GET", "/watch?v=", text_response("", status=status))
    with pytest.raises(error):
        fetch_api_key(transport, VIDEO_ID)
