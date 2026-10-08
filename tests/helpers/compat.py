"""A fake YouTube for utmax.compat, and a requests.Session look-alike over FakeTransport."""

from __future__ import annotations

from typing import Any

from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from tests.helpers.youtube import player_payload
from utmax.transport import HttpRequest, HttpResponse

VIDEO = "GJLlxj_dtq8"
TRACKS: tuple[tuple[str, str, bool], ...] = (
    ("zh", "Chinese", False),
    ("de", "German", False),
    ("en", "English", False),
    ("hi", "Hindi", False),
    ("ja", "Japanese", False),
    ("ko", "Korean", False),
    ("es", "Spanish", False),
    ("cs", "Czech", False),
    ("en", "English (auto-generated)", True),
)
TRANSLATION_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("ar", "Arabic"),
    ("de", "German"),
    ("en", "English"),
)
TRANSCRIPT_XML = (
    '<?xml version="1.0" encoding="utf-8" ?><transcript>'
    '<text start="0" dur="1.5">Welcome back to the channel</text>'
    '<text start="1.5" dur="4.2">today we &lt;i&gt;really&lt;/i&gt; build &amp;quot;it&amp;quot;</text>'
    '<text start="5" dur="0.5"></text>'
    '<text start="5.7" dur="3.239">see you next time</text>'
    "</transcript>"
)
RAW_DATA = [
    {"text": "Welcome back to the channel", "start": 0.0, "duration": 1.5},
    {"text": 'today we really build "it"', "start": 1.5, "duration": 4.2},
    {"text": "see you next time", "start": 5.7, "duration": 3.239},
]


def xml_response(text: str, *, status: int = 200) -> HttpResponse:
    return text_response(text, status=status, content_type="text/xml; charset=UTF-8")


def compat_youtube(
    *,
    tracks: tuple[tuple[str, str, bool], ...] = TRACKS,
    xml: str = TRANSCRIPT_XML,
    **player: Any,
) -> FakeTransport:
    """One video (``VIDEO``) with ``tracks``; every caption request answers ``xml``."""
    transport = FakeTransport()
    payload = player_payload(
        video_id=VIDEO, tracks=tracks, translation_languages=TRANSLATION_LANGUAGES, **player
    )
    transport.add("POST", "/youtubei/v1/player", json_response(payload))
    transport.add("GET", "/api/timedtext", xml_response(xml), repeat=True)
    return transport


class FakeResponse:
    """The parts of a ``requests.Response`` that utmax.compat reads."""

    def __init__(self, response: HttpResponse) -> None:
        self.status_code = response.status
        self.headers = dict(response.headers)
        self.content = response.body
        self.url = response.url


class FakeSession:
    """Just enough of ``requests.Session``: ``request()``, ``headers`` and ``proxies``.

    Requests go to ``transport`` with the session headers merged in, as requests does.
    """

    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        self.headers: dict[str, str] = {"User-Agent": "python-requests/2.34"}
        self.proxies: dict[str, str] = {}
        self.timeouts: list[float | None] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.timeouts.append(timeout)
        merged = {**self.headers, **(headers or {})}
        verb = "POST" if method == "POST" else "GET"
        return FakeResponse(self.transport.send(HttpRequest(verb, url, merged, data)))
