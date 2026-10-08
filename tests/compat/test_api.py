"""youtube-transcript-api 1.2.4's API tests, run against utmax.compat.

YouTube is faked behind a requests.Session look-alike (``http_client``). utmax asks InnerTube
without an API key and reads the watch page only when every client fails, so the tests that
script the watch page first make the player requests fail; the request counts are utmax's.
"""

from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.helpers.compat import (
    RAW_DATA,
    TRANSCRIPT_XML,
    VIDEO,
    FakeSession,
    compat_youtube,
    xml_response,
)
from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from tests.helpers.youtube import player_payload
from utmax.compat import _bridge
from utmax.compat._api import YouTubeTranscriptApi
from utmax.compat._errors import (
    AgeRestricted,
    FailedToCreateConsentCookie,
    InvalidVideoId,
    IpBlocked,
    NoTranscriptFound,
    NotTranslatable,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    TranslationLanguageNotAvailable,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeRequestFailed,
)
from utmax.compat._transcripts import FetchedTranscript, FetchedTranscriptSnippet
from utmax.compat.proxies import GenericProxyConfig, WebshareProxyConfig
from utmax.transport import HttpRequest, HttpResponse

WATCH_HTML = '<script>ytcfg.set({"INNERTUBE_API_KEY": "AIzaTestKey_123-abc"});</script>'
CONSENT_HTML = (
    '<form action="https://consent.youtube.com/s" method="POST">'
    '<input type="hidden" name="v" value="cb.20210328-17-p0.de+FX+119"></form>'
)
CAPTCHA_HTML = '<form><div class="g-recaptcha" data-sitekey="x"></div></form>'
BOT_CHECK = player_payload(
    video_id=VIDEO, status="LOGIN_REQUIRED", reason="Sign in to confirm you’re not a bot"
)


def reference() -> FetchedTranscript:
    return FetchedTranscript(
        snippets=[FetchedTranscriptSnippet(**line) for line in RAW_DATA],
        video_id=VIDEO,
        language="English",
        language_code="en",
        is_generated=False,
    )


def api(transport: FakeTransport, **options: Any) -> YouTubeTranscriptApi:
    return YouTubeTranscriptApi(http_client=FakeSession(transport), **options)


def failing_players(transport: FakeTransport) -> FakeTransport:
    """Every InnerTube client answers HTTP 500, so utmax reads the watch page."""
    failure = text_response("", status=500)
    transport.add("POST", "/youtubei/v1/player?prettyPrint=false", failure, failure, failure)
    return transport


def caption_languages(transport: FakeTransport) -> list[str]:
    return [url.split("lang=")[1].split("&")[0] for url in transport.urls("GET") if "lang=" in url]


class MeetingTransport(FakeTransport):
    """Holds every request until ``threads`` of them are in flight, then answers each with the
    video it names.

    The threads of a test are thus inside the player request together, and again inside the
    caption download, and every answer belongs to the video its request asked for. A call that
    keeps its video on the shared instance instead of on its own stack would hand one thread
    another's video, and the answers would show it.
    """

    def __init__(self, threads: int) -> None:
        super().__init__()
        self._meeting = threading.Barrier(threads, timeout=5)

    def send(self, request: HttpRequest) -> HttpResponse:
        with self._lock:
            self.requests.append(request)
        if request.method == "POST" and "/youtubei/v1/player" in request.url:
            video_id = json.loads(request.body or b"{}")["videoId"]
            reply = json_response(player_payload(video_id=video_id))
        elif request.method == "GET" and "/api/timedtext" in request.url:
            video_id = parse_qs(urlsplit(request.url).query)["v"][0]
            cue = f'<text start="0" dur="1.5">{video_id}</text>'
            reply = xml_response(f"<transcript>{cue}</transcript>")
        else:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        self._meeting.wait()
        return reply


def test_fetch() -> None:
    assert api(compat_youtube()).fetch(VIDEO) == reference()


def test_fetch_formatted() -> None:
    transcript = api(compat_youtube()).fetch(VIDEO, preserve_formatting=True)

    expected = reference()
    expected[1].text = 'today we <i>really</i> build "it"'
    assert transcript == expected


def test_fetch__from_the_next_client_when_the_first_fails() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", text_response("", status=500))
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload(video_id=VIDEO)))
    transport.add("GET", "/api/timedtext", xml_response(TRANSCRIPT_XML))

    transcript = api(transport).fetch(VIDEO)

    assert transcript.snippets == reference().snippets


def test_fetch__accepts_urls() -> None:
    transcript = api(compat_youtube()).fetch(f"https://www.youtube.com/watch?v={VIDEO}&t=42")

    assert transcript.video_id == VIDEO


def test_list() -> None:
    transcript_list = api(compat_youtube()).list(VIDEO)

    language_codes = [transcript.language_code for transcript in transcript_list]

    assert language_codes == ["zh", "de", "en", "hi", "ja", "ko", "es", "cs", "en"]


def test_list__find_manually_created() -> None:
    transcript_list = api(compat_youtube()).list(VIDEO)

    assert not transcript_list.find_manually_created_transcript(["cs"]).is_generated


def test_list__find_generated() -> None:
    transcript_list = api(compat_youtube()).list(VIDEO)

    with pytest.raises(NoTranscriptFound):
        transcript_list.find_generated_transcript(["cs"])

    assert transcript_list.find_generated_transcript(["en"]).is_generated


def test_list__url_as_video_id() -> None:
    transport = FakeTransport()

    with pytest.raises(InvalidVideoId):
        api(transport).list(f"https://www.youtube.com/youtubei/v1/player?v={VIDEO}")
    assert transport.requests == []


def test_translate_transcript() -> None:
    transcript = api(compat_youtube()).list(VIDEO).find_transcript(["en"])

    translated_transcript = transcript.translate("ar")

    assert translated_transcript.language_code == "ar"
    assert "&tlang=ar" in translated_transcript._url


def test_translate_transcript__translation_language_not_available() -> None:
    transcript = api(compat_youtube()).list(VIDEO).find_transcript(["en"])

    with pytest.raises(TranslationLanguageNotAvailable):
        transcript.translate("xyz")


def test_translate_transcript__not_translatable() -> None:
    transcript = api(compat_youtube()).list(VIDEO).find_transcript(["en"])
    transcript.translation_languages = []

    with pytest.raises(NotTranslatable):
        transcript.translate("af")


def test_fetch__correct_language_is_used() -> None:
    transport = compat_youtube()

    api(transport).fetch(VIDEO, ["de", "en"])

    assert caption_languages(transport) == ["de"]


def test_fetch__fallback_language_is_used() -> None:
    transport = compat_youtube(tracks=(("nl", "Dutch", False), ("en", "English", False)))

    api(transport).fetch(VIDEO, ["de", "en"])

    assert caption_languages(transport) == ["en"]


def test_fetch__exact_language_codes_only() -> None:
    transport = compat_youtube(tracks=(("de-DE", "German (Germany)", False),))

    with pytest.raises(NoTranscriptFound):
        api(transport).fetch(VIDEO, ["de"])


def test_fetch__create_consent_cookie_if_needed() -> None:
    transport = failing_players(FakeTransport())
    transport.add("GET", "/watch?v=", text_response(CONSENT_HTML), text_response(WATCH_HTML))
    transport.add("POST", "key=AIzaTestKey_123-abc", json_response(player_payload(video_id=VIDEO)))
    transport.add("GET", "/api/timedtext", xml_response(TRANSCRIPT_XML))

    api(transport).fetch(VIDEO)

    watch_pages = [request for request in transport.requests if "/watch?v=" in request.url]
    assert len(watch_pages) == 2
    assert "Cookie" not in watch_pages[0].headers
    assert watch_pages[1].headers["Cookie"] == "CONSENT=YES+cb.20210328-17-p0.de+FX+119"


def test_fetch__exception_if_create_consent_cookie_failed() -> None:
    transport = failing_players(FakeTransport())
    transport.add("GET", "/watch?v=", text_response(CONSENT_HTML), text_response(CONSENT_HTML))

    with pytest.raises(FailedToCreateConsentCookie):
        api(transport).fetch(VIDEO)


def test_fetch__exception_if_consent_cookie_age_invalid() -> None:
    transport = failing_players(FakeTransport())
    transport.add(
        "GET", "/watch?v=", text_response('<form action="https://consent.youtube.com/s">')
    )

    with pytest.raises(FailedToCreateConsentCookie):
        api(transport).fetch(VIDEO)


def test_fetch__exception_if_video_unavailable() -> None:
    transport = FakeTransport()
    unavailable = player_payload(
        video_id=VIDEO, status="ERROR", reason="This video is unavailable", captions=False
    )
    transport.add("POST", "/youtubei/v1/player", json_response(unavailable))

    with pytest.raises(VideoUnavailable):
        api(transport).fetch(VIDEO)


def test_fetch__exception_if_the_id_cannot_be_a_video() -> None:
    transport = FakeTransport()

    with pytest.raises(VideoUnavailable):
        api(transport).fetch("abc")
    assert transport.requests == []


def test_fetch__exception_if_youtube_request_fails() -> None:
    transport = failing_players(FakeTransport())
    transport.add("GET", "/watch?v=", text_response("", status=500))

    with pytest.raises(YouTubeRequestFailed) as caught:
        api(transport).fetch(VIDEO)

    assert "Request to YouTube failed: " in str(caught.value)


def test_fetch__exception_if_youtube_request_limit_reached() -> None:
    transport = failing_players(FakeTransport())
    transport.add("GET", "/watch?v=", text_response(CAPTCHA_HTML))

    with pytest.raises(IpBlocked):
        api(transport).fetch(VIDEO)


def test_fetch__exception_if_timedtext_request_limit_reached() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload(video_id=VIDEO)))
    transport.add("GET", "/api/timedtext", xml_response("", status=429))

    with pytest.raises(IpBlocked):
        api(transport).fetch(VIDEO)


def test_fetch__exception_if_age_restricted() -> None:
    transport = FakeTransport()
    restricted = player_payload(
        video_id=VIDEO,
        status="LOGIN_REQUIRED",
        reason="This video may be inappropriate for some users.",
        captions=False,
    )
    transport.add("POST", "/youtubei/v1/player", json_response(restricted), repeat=True)

    with pytest.raises(AgeRestricted):
        api(transport).fetch(VIDEO)


def test_fetch__exception_if_po_token_required() -> None:
    transport = FakeTransport()
    payload = player_payload(video_id=VIDEO)
    tracks = payload["captions"]["playerCaptionsTracklistRenderer"]["captionTracks"]
    for track in tracks:
        track["baseUrl"] += "&exp=xpe"
    transport.add("POST", "/youtubei/v1/player", json_response(payload))

    with pytest.raises(PoTokenRequired):
        api(transport).fetch(VIDEO)
    assert transport.urls("GET") == []


def test_fetch__exception_request_blocked() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(BOT_CHECK), repeat=True)

    with pytest.raises(RequestBlocked) as caught:
        api(transport).fetch(VIDEO)

    assert "YouTube is blocking requests from your IP" in str(caught.value)


def test_fetch__exception_unplayable() -> None:
    transport = FakeTransport()
    unplayable = player_payload(
        video_id=VIDEO,
        status="UNPLAYABLE",
        reason="Custom Reason",
        sub_reasons=("Sub Reason 1", "Sub Reason 2"),
        captions=False,
    )
    transport.add("POST", "/youtubei/v1/player", json_response(unplayable), repeat=True)

    with pytest.raises(VideoUnplayable) as caught:
        api(transport).fetch(VIDEO)

    exception = caught.value
    assert exception.reason == "Custom Reason"
    assert exception.sub_reasons == ["Sub Reason 1", "Sub Reason 2"]
    assert "Custom Reason" in str(exception)


@pytest.mark.parametrize("renderer", [None, {"translationLanguages": []}])
def test_fetch__exception_if_transcripts_disabled(renderer: dict[str, Any] | None) -> None:
    transport = FakeTransport()
    payload = player_payload(video_id=VIDEO, captions=False)
    if renderer is not None:
        payload["captions"] = {"playerCaptionsTracklistRenderer": renderer}
    transport.add("POST", "/youtubei/v1/player", json_response(payload))

    with pytest.raises(TranscriptsDisabled):
        api(transport).fetch(VIDEO)


def test_fetch__exception_if_language_unavailable() -> None:
    with pytest.raises(NoTranscriptFound) as caught:
        api(compat_youtube()).fetch(VIDEO, languages=["cz"])

    assert "No transcripts were found for" in str(caught.value)


def test_fetch__with_proxy() -> None:
    session = FakeSession(compat_youtube())
    proxy_config = GenericProxyConfig(
        http_url="http://localhost:8080",
        https_url="http://localhost:8080",
    )

    transcript = YouTubeTranscriptApi(proxy_config=proxy_config, http_client=session).fetch(VIDEO)

    assert transcript == reference()
    assert session.proxies == {"http": "http://localhost:8080", "https": "http://localhost:8080"}
    assert session.headers["Accept-Language"] == "en-US"
    assert "Connection" not in session.headers


def test_fetch__with_proxy_prevent_alive_connections() -> None:
    transport = compat_youtube()
    proxy_config = WebshareProxyConfig(proxy_username="username", proxy_password="password")

    YouTubeTranscriptApi(proxy_config=proxy_config, http_client=FakeSession(transport)).fetch(VIDEO)

    assert transport.requests[-1].headers["Connection"] == "close"


def test_fetch__with_proxy_retry_when_blocked() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", *[json_response(BOT_CHECK)] * 3)
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload(video_id=VIDEO)))
    transport.add("GET", "/api/timedtext", xml_response(TRANSCRIPT_XML))
    proxy_config = WebshareProxyConfig(proxy_username="username", proxy_password="password")

    transcript = api(transport, proxy_config=proxy_config).fetch(VIDEO)

    assert transcript == reference()
    assert len(transport.requests) == 3 + 1 + 1


def test_fetch__with_webshare_proxy_reraise_when_blocked() -> None:
    retries = 5
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(BOT_CHECK), repeat=True)
    proxy_config = WebshareProxyConfig(
        proxy_username="username",
        proxy_password="password",
        retries_when_blocked=retries,
    )

    with pytest.raises(RequestBlocked) as caught:
        api(transport, proxy_config=proxy_config).fetch(VIDEO)

    assert len(transport.requests) == 3 * (retries + 1)
    assert caught.value._proxy_config == proxy_config
    assert "Webshare" in str(caught.value)


def test_fetch__with_generic_proxy_reraise_when_blocked() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(BOT_CHECK), repeat=True)
    proxy_config = GenericProxyConfig(
        http_url="http://localhost:8080",
        https_url="http://localhost:8080",
    )

    with pytest.raises(RequestBlocked) as caught:
        api(transport, proxy_config=proxy_config).fetch(VIDEO)

    assert len(transport.requests) == 3
    assert caught.value._proxy_config == proxy_config
    assert "YouTube is blocking your requests" in str(caught.value)


def test_without_an_http_client_utmax_sends_the_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = FakeTransport()
    transport.add(
        "POST", "/youtubei/v1/player", json_response(player_payload(video_id=VIDEO)), repeat=True
    )
    transport.add("GET", "/api/timedtext", xml_response(TRANSCRIPT_XML))
    proxies: list[str | None] = []

    def fake_urllib(*, proxy: str | None, timeout: float) -> FakeTransport:
        proxies.append(proxy)
        return transport

    monkeypatch.setattr(_bridge, "UrllibTransport", fake_urllib)

    assert YouTubeTranscriptApi().fetch(VIDEO) == reference()
    YouTubeTranscriptApi(GenericProxyConfig(http_url="http://localhost:8080")).list(VIDEO)
    assert proxies == [None, "http://localhost:8080"]


def test_one_instance_serves_many_threads() -> None:
    video_ids = [f"vid_{index:07d}" for index in range(8)]
    ytt_api = api(MeetingTransport(threads=len(video_ids)))
    results: dict[str, FetchedTranscript] = {}

    def work(video_id: str) -> None:
        results[video_id] = ytt_api.fetch(video_id)

    threads = [threading.Thread(target=work, args=(video_id,)) for video_id in video_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == {
        video_id: FetchedTranscript(
            snippets=[FetchedTranscriptSnippet(text=video_id, start=0.0, duration=1.5)],
            video_id=video_id,
            language="English",
            language_code="en",
            is_generated=False,
        )
        for video_id in video_ids
    }
