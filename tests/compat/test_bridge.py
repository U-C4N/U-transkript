"""How utmax.compat reaches YouTube: transports, video IDs and the error bridge."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.compat import VIDEO, FakeSession, compat_youtube, xml_response
from tests.helpers.fake_transport import FakeTransport, json_response
from tests.helpers.youtube import player_payload
from utmax import errors
from utmax.adapters.http import RetryingTransport
from utmax.compat import _bridge
from utmax.compat._bridge import (
    TIMEOUT,
    Connection,
    SessionTransport,
    compat_error,
    connection_for,
    make_transport,
    video_id_of,
)
from utmax.compat._errors import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    FailedToCreateConsentCookie,
    InvalidVideoId,
    IpBlocked,
    PoTokenRequired,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)
from utmax.compat.proxies import (
    GenericProxyConfig,
    InvalidProxyConfig,
    ProxyConfig,
    WebshareProxyConfig,
)
from utmax.transport import HttpRequest, HttpResponse

PLAYER_URL = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
CAPTION_URL = f"https://www.youtube.com/api/timedtext?v={VIDEO}&lang=en&fmt=srv3"
BOT_CHECK = player_payload(
    video_id=VIDEO, status="LOGIN_REQUIRED", reason="Sign in to confirm you’re not a bot"
)


# How requests and its relatives word a failed request: the error repeats the URL, or its path
# and query. Placeholders: {url} is the request's URL, {path} its path and query, {query} its query.
SESSION_FAILURES = (
    "HTTPSConnectionPool(host='www.youtube.com', port=443): Max retries exceeded with url: "
    "{path} (Caused by NewConnectionError('connection reset by peer'))",
    "connection reset by peer for url: {url}",
    "connection reset by peer for url '{url}'",
    "connection reset by peer (url: {path})",
    "connection reset by peer, params {query}",
)


class BrokenSession:
    """Fails with ``text``, filled in with the URL, path and query of the request."""

    def __init__(self, text: str) -> None:
        self.headers: dict[str, str] = {}
        self._text = text

    def request(self, method: str, url: str, **options: Any) -> None:
        path = url.removeprefix("https://www.youtube.com")
        raise ConnectionError(self._text.format(url=url, path=path, query=url.partition("?")[2]))


def test_session_transport_sends_every_request_through_the_session() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/player",
        HttpResponse(
            200,
            PLAYER_URL,
            {"Content-Type": "application/json", "Content-Encoding": "gzip", "Content-Length": "2"},
            b'{"ok": true}',
        ),
    )
    session = FakeSession(transport)

    response = SessionTransport(session).send(
        HttpRequest("POST", PLAYER_URL, {"X-Test": "1"}, b"{}")
    )

    assert (response.status, response.json()) == (200, {"ok": True})
    assert response.header("content-encoding") is None
    assert response.header("content-length") is None
    assert response.content_type == "application/json"
    sent = transport.requests[0]
    assert (sent.method, sent.url, sent.body) == ("POST", PLAYER_URL, b"{}")
    assert (sent.headers["X-Test"], sent.headers["User-Agent"]) == ("1", "python-requests/2.34")
    assert session.timeouts == [TIMEOUT]


def test_session_failures_become_network_errors_without_the_query() -> None:
    signed = f"{CAPTION_URL}&ip=203.0.113.7&expire=1760000000&sig=secret"
    unsigned = "https://www.youtube.com/api/timedtext"

    for text in SESSION_FAILURES:
        with pytest.raises(errors.NetworkError, match="connection reset by peer") as caught:
            SessionTransport(BrokenSession(text)).send(HttpRequest("GET", signed))
        mapped = compat_error(caught.value, VIDEO)

        assert isinstance(caught.value.__cause__, ConnectionError)
        assert "sig=secret" in str(caught.value.__cause__)
        assert isinstance(mapped, YouTubeRequestFailed)
        for message in (str(caught.value), mapped.reason, str(mapped)):
            assert "secret" not in message
            assert "203.0.113.7" not in message

    with pytest.raises(errors.NetworkError) as plain:
        SessionTransport(BrokenSession(SESSION_FAILURES[0])).send(HttpRequest("GET", unsigned))
    # Other URLs in the text (a redirect's, say) lose their query up to a quote, a closing
    # parenthesis, whitespace or the end, whatever the request's own URL is.
    redirects = (
        "moved to 'https://a.test/x?v=1&sig=1' (https://b.test/y?v=2&sig=2) and "
        "https://c.test/z?v=3&sig=3 then https://d.test/w?v=4&sig=4"
    )

    assert str(plain.value) == f"Could not complete GET {unsigned}: {plain.value.__cause__}"
    assert _bridge._without_query(redirects, unsigned) == (
        "moved to 'https://a.test/x' (https://b.test/y) and https://c.test/z then https://d.test/w"
    )


def test_make_transport_uses_the_http_client_as_given() -> None:
    session = FakeSession(FakeTransport())

    transport = make_transport(session, GenericProxyConfig(https_url="socks5://proxy:1080"))

    assert isinstance(transport, SessionTransport)


def test_make_transport_gives_utmax_the_https_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, Any]] = []

    def fake_urllib(**options: Any) -> FakeTransport:
        created.append(options)
        return FakeTransport()

    monkeypatch.setattr(_bridge, "UrllibTransport", fake_urllib)

    plain = make_transport(None, None)
    proxied = make_transport(None, WebshareProxyConfig("user", "password"))

    assert isinstance(plain, RetryingTransport)
    assert isinstance(proxied, RetryingTransport)
    assert created == [
        {"proxy": None, "timeout": TIMEOUT},
        {"proxy": "http://user-rotate:password@p.webshare.io:80/", "timeout": TIMEOUT},
    ]


@pytest.mark.parametrize("proxy", ["https://proxy.test:443", "socks5://proxy.test:1080"])
def test_utmax_alone_supports_only_http_proxies(proxy: str) -> None:
    with pytest.raises(InvalidProxyConfig, match=r"pass http_client=requests\.Session"):
        make_transport(None, GenericProxyConfig(http_url=proxy, https_url=proxy))


@pytest.mark.parametrize(
    "value",
    [VIDEO, f"https://www.youtube.com/watch?v={VIDEO}", f"youtu.be/{VIDEO}", f" {VIDEO} "],
)
def test_video_ids_and_urls_are_accepted(value: str) -> None:
    assert video_id_of(value) == VIDEO


def test_inputs_without_a_video_raise_what_youtube_transcript_api_raises() -> None:
    with pytest.raises(VideoUnavailable) as unavailable:
        video_id_of("abc")
    with pytest.raises(InvalidVideoId) as invalid:
        video_id_of(f"https://www.youtube.com/youtubei/v1/player?v={VIDEO}")

    assert unavailable.value.video_id == "abc"
    assert invalid.value.video_id == f"https://www.youtube.com/youtubei/v1/player?v={VIDEO}"
    assert isinstance(unavailable.value.__cause__, errors.InvalidVideoId)
    assert isinstance(invalid.value.__cause__, errors.InvalidVideoId)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (errors.VideoUnavailable("gone"), VideoUnavailable),
        (errors.AgeRestricted("age"), AgeRestricted),
        (errors.PoTokenRequired("pot"), PoTokenRequired),
        (errors.FailedToCreateConsentCookie("consent"), FailedToCreateConsentCookie),
        (errors.YouTubeDataUnparsable("garbage"), YouTubeDataUnparsable),
        (errors.TranscriptsDisabled("none"), TranscriptsDisabled),
        (errors.InvalidVideoId("bad"), InvalidVideoId),
        (errors.RequestBlocked("bot"), RequestBlocked),
        (errors.IpBlocked("429"), IpBlocked),
        (errors.YouTubeRequestFailed("HTTP 500", status_code=500), YouTubeRequestFailed),
        (errors.NetworkError("Could not complete GET /x: timed out"), YouTubeRequestFailed),
        (errors.InvalidOption("odd"), YouTubeRequestFailed),
    ],
)
def test_utmax_errors_map_to_youtube_transcript_api_errors(
    error: errors.UTMaxError, expected: type[CouldNotRetrieveTranscript]
) -> None:
    mapped = compat_error(error, VIDEO)

    assert type(mapped) is expected
    assert mapped.video_id == VIDEO


def test_mapped_errors_keep_what_youtube_said() -> None:
    config = GenericProxyConfig(http_url="http://localhost:8080")
    blocked = compat_error(errors.IpBlocked("429"), VIDEO, config)
    failed = compat_error(errors.NetworkError("timed out"), VIDEO)
    unplayable = compat_error(
        errors.VideoUnplayable("x", reason="Custom Reason", sub_reasons=("a", "b")), VIDEO
    )
    silent = compat_error(errors.VideoUnplayable("x"), VIDEO)

    assert isinstance(blocked, IpBlocked)
    assert blocked._proxy_config is config
    assert isinstance(failed, YouTubeRequestFailed)
    assert failed.reason == "timed out"
    assert isinstance(unplayable, VideoUnplayable)
    assert (unplayable.reason, unplayable.sub_reasons) == ("Custom Reason", ["a", "b"])
    assert isinstance(silent, VideoUnplayable)
    assert silent.reason is None


def test_a_player_without_captions_means_transcripts_are_disabled() -> None:
    transport = FakeTransport()
    transport.add(
        "POST", "/youtubei/v1/player", json_response(player_payload(video_id=VIDEO, captions=False))
    )

    with pytest.raises(TranscriptsDisabled):
        Connection(transport).player(VIDEO)


def test_blocked_requests_are_retried_as_the_proxy_config_says() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(BOT_CHECK), repeat=True)
    config = GenericProxyConfig(http_url="http://localhost:8080")
    config_with_retries = WebshareProxyConfig("user", "password", retries_when_blocked=2)

    with pytest.raises(RequestBlocked) as generic:
        Connection(transport, proxy_config=config).player(VIDEO)
    once = len(transport.requests)
    with pytest.raises(RequestBlocked) as webshare:
        Connection(transport, proxy_config=config_with_retries).player(VIDEO)

    assert generic.value._proxy_config is config
    assert webshare.value._proxy_config is config_with_retries
    assert len(transport.requests) - once == 3 * once
    assert isinstance(generic.value.__cause__, errors.RequestBlocked)


def test_captions_are_downloaded_as_legacy_xml() -> None:
    transport = compat_youtube()
    connection = Connection(transport, proxy_config=GenericProxyConfig(http_url="http://p:1"))

    video_id, player = connection.player(f"https://youtu.be/{VIDEO}")
    text = connection.caption_text(CAPTION_URL, video_id)

    assert video_id == VIDEO
    assert player.caption_tracks is not None
    assert text.startswith("<?xml")
    assert transport.urls("GET") == [f"https://www.youtube.com/api/timedtext?v={VIDEO}&lang=en"]


def test_caption_rate_limits_are_ip_blocks_without_proxy_advice() -> None:
    transport = FakeTransport()
    transport.add("GET", "/api/timedtext", xml_response("", status=429))
    connection = Connection(transport, proxy_config=GenericProxyConfig(http_url="http://p:1"))

    with pytest.raises(IpBlocked) as caught:
        connection.caption_text(CAPTION_URL, VIDEO)

    assert caught.value._proxy_config is None


def test_transcripts_find_their_connection() -> None:
    connection = Connection(FakeTransport())
    session = FakeSession(FakeTransport())

    assert connection_for(connection) is connection
    assert isinstance(connection_for(session), Connection)
    assert isinstance(connection_for(None), Connection)


class OneSchemeProxy(ProxyConfig):
    """A custom configuration that names only some of requests' schemes."""

    def __init__(self, proxies: dict[str, str]) -> None:
        self.proxies = proxies

    def to_requests_dict(self) -> Any:
        return self.proxies


def test_a_custom_proxy_config_may_name_one_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str | None] = []

    def fake_urllib(*, proxy: str | None, timeout: float) -> FakeTransport:
        created.append(proxy)
        return FakeTransport()

    monkeypatch.setattr(_bridge, "UrllibTransport", fake_urllib)

    make_transport(None, OneSchemeProxy({"http": "http://localhost:8080"}))
    with pytest.raises(InvalidProxyConfig, match=r"OneSchemeProxy\.to_requests_dict\(\) names no"):
        make_transport(None, OneSchemeProxy({}))

    assert created == ["http://localhost:8080"]


def test_padded_urls_without_a_video_are_invalid_video_ids() -> None:
    with pytest.raises(InvalidVideoId):
        video_id_of(" https://www.youtube.com/playlist?list=PL1234567890ab ")
