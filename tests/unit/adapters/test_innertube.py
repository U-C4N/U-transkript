"""Tests for the InnerTube adapter."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from tests.helpers.youtube import MANUAL_JSON3, VIDEO_ID, player_payload, streaming_data
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.clients import IOS
from utmax.errors import (
    AgeRestricted,
    IpBlocked,
    PoTokenRequired,
    UTMaxError,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeDataUnparsable,
    YouTubeRequestFailed,
)
from utmax.transport import HttpResponse

WATCH_HTML = '<script>ytcfg.set({"INNERTUBE_API_KEY": "AIzaTestKey_123-abc"});</script>'
CAPTION_URL = f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=srv3"


def client_names(transport: FakeTransport) -> list[str]:
    return [
        json.loads(r.body or b"{}")["context"]["client"]["clientName"]
        for r in transport.requests
        if r.method == "POST"
    ]


def test_player_uses_the_first_profile_when_it_works() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload()))
    player = InnerTubeClient(transport).player(VIDEO_ID)
    assert player.video.title.startswith("Rick Astley")
    assert len(player.caption_tracks or ()) == 6
    (request,) = transport.requests
    assert request.url == "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
    body = json.loads(request.body or b"{}")
    assert body["videoId"] == VIDEO_ID
    assert body["contentCheckOk"] is True
    assert body["context"]["client"]["clientName"] == "ANDROID"
    assert request.headers["X-YouTube-Client-Name"] == "3"


@pytest.mark.parametrize(
    "first_reply",
    [
        text_response("bad request", status=400),
        text_response("server error", status=503),
        text_response("<html>not json</html>"),
        json_response(["not", "an", "object"]),
        json_response(player_payload(status="UNPLAYABLE", reason="Not available on this app")),
        json_response(
            player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm you're not a bot")
        ),
    ],
)
def test_falls_back_to_the_next_profile(first_reply: HttpResponse) -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", first_reply, json_response(player_payload()))
    assert InnerTubeClient(transport).player(VIDEO_ID).playability.status == "OK"
    assert client_names(transport) == ["ANDROID", "IOS"]


def test_the_first_error_wins_when_every_profile_is_unplayable() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/player",
        *(
            json_response(player_payload(status="UNPLAYABLE", reason=f"reason {i}"))
            for i in range(3)
        ),
    )
    with pytest.raises(VideoUnplayable, match="reason 0"):
        InnerTubeClient(transport).player(VIDEO_ID)
    assert client_names(transport) == ["ANDROID", "IOS", "ANDROID_VR"]


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (text_response("slow down", status=429), IpBlocked),
        (
            json_response(player_payload(status="ERROR", reason="This video is unavailable")),
            VideoUnavailable,
        ),
        (
            json_response(
                player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm your age")
            ),
            AgeRestricted,
        ),
    ],
)
def test_final_errors_stop_the_chain(reply: HttpResponse, error: type[UTMaxError]) -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", reply)
    with pytest.raises(error):
        InnerTubeClient(transport).player(VIDEO_ID)
    assert len(transport.requests) == 1


def test_block_retries_repeat_the_same_profile() -> None:
    transport = FakeTransport()
    blocked = text_response("", status=429)
    transport.add("POST", "/player", blocked, blocked, json_response(player_payload()))
    InnerTubeClient(transport, block_retries=2).player(VIDEO_ID)
    assert client_names(transport) == ["ANDROID", "ANDROID", "ANDROID"]


def test_watch_page_fallback_when_every_profile_fails_at_the_http_level() -> None:
    transport = FakeTransport()
    transport.add("POST", "&key=AIzaTestKey_123-abc", json_response(player_payload()))
    transport.add("POST", "/player", *[text_response("forbidden", status=403)] * 3)
    transport.add("GET", "/watch?v=", text_response(WATCH_HTML))
    player = InnerTubeClient(transport).player(VIDEO_ID)
    assert player.playability.status == "OK"
    assert [r.method for r in transport.requests] == ["POST", "POST", "POST", "GET", "POST"]
    assert transport.urls()[-1].endswith("/player?prettyPrint=false&key=AIzaTestKey_123-abc")
    assert client_names(transport)[-1] == "ANDROID"


def test_player_json_returns_the_raw_response_of_one_profile() -> None:
    transport = FakeTransport()
    transport.add(
        "POST", "/player", json_response(player_payload()), text_response("x", status=404)
    )
    client = InnerTubeClient(transport)
    assert client.player_json(IOS, VIDEO_ID)["videoDetails"]["videoId"] == VIDEO_ID
    assert client_names(transport) == ["IOS"]
    with pytest.raises(YouTubeRequestFailed) as caught:
        client.player_json(IOS, VIDEO_ID)
    assert caught.value.status_code == 404


def test_fetch_captions_requests_json3() -> None:
    transport = FakeTransport()
    transport.add("GET", "/api/timedtext", json_response(MANUAL_JSON3))
    response = InnerTubeClient(transport).fetch_captions(CAPTION_URL, video_id=VIDEO_ID)
    assert response.status == 200
    assert transport.urls() == [
        f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=json3"
    ]


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("https://evil.example/api/timedtext?v=x", YouTubeDataUnparsable),
        (f"{CAPTION_URL}&exp=xpe", PoTokenRequired),
    ],
)
def test_fetch_captions_refuses_unsafe_urls_without_a_request(
    url: str, error: type[UTMaxError]
) -> None:
    transport = FakeTransport()
    with pytest.raises(error):
        InnerTubeClient(transport).fetch_captions(url, video_id=VIDEO_ID)
    assert transport.requests == []


def test_caption_rate_limits_and_http_errors() -> None:
    transport = FakeTransport()
    transport.add(
        "GET",
        "/api/timedtext",
        text_response("", status=429),
        text_response("", status=429),
        text_response("", status=404),
    )
    client = InnerTubeClient(transport)
    with pytest.raises(IpBlocked) as plain:
        client.fetch_captions(CAPTION_URL, video_id=VIDEO_ID)
    assert plain.value.suggestion == IpBlocked.suggestion
    with pytest.raises(IpBlocked) as translated:
        client.fetch_captions(f"{CAPTION_URL}&tlang=tr", video_id=VIDEO_ID)
    assert "AI translation" in translated.value.suggestion
    with pytest.raises(YouTubeRequestFailed) as missing:
        client.fetch_captions(CAPTION_URL, video_id=VIDEO_ID)
    assert missing.value.status_code == 404


def streams_payload(*, direct: bool) -> dict[str, Any]:
    data = streaming_data()
    if not direct:
        ciphered = [
            {key: value for key, value in entry.items() if key != "url"}
            | {"signatureCipher": "s=1"}
            for entry in data["adaptiveFormats"]
        ]
        data = {**data, "formats": [], "adaptiveFormats": ciphered}
    return player_payload(streaming_data=data)


def test_stream_players_skip_profiles_without_direct_mp4_urls() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/player",
        json_response(streams_payload(direct=False)),
        json_response(streams_payload(direct=True)),
    )
    player = InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["ANDROID_VR", "ANDROID"]
    assert any(stream.url for stream in player.streams)


def test_stream_players_fall_back_to_the_watch_page_then_give_up() -> None:
    transport = FakeTransport()
    transport.add(
        "POST", "/youtubei/v1/player", json_response(streams_payload(direct=False)), repeat=True
    )
    transport.add("GET", "/watch", text_response(WATCH_HTML))
    with pytest.raises(YouTubeDataUnparsable, match="no direct MP4 stream URLs"):
        InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["ANDROID_VR", "ANDROID", "IOS", "ANDROID"]


def test_caption_players_do_not_need_streams() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload()))
    assert InnerTubeClient(transport).player(VIDEO_ID).streams == ()


def test_a_bot_check_on_one_stream_profile_moves_on_to_the_next() -> None:
    blocked = player_payload(status="LOGIN_REQUIRED", reason="Sign in to confirm you're not a bot")
    transport = FakeTransport()
    transport.add(
        "POST",
        "/youtubei/v1/player",
        json_response(blocked),
        json_response(streams_payload(direct=True)),
    )
    InnerTubeClient(transport).player(VIDEO_ID, purpose="streams")
    assert client_names(transport) == ["ANDROID_VR", "ANDROID"]
