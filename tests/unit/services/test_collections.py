"""Tests for listing playlists and channels over recorded and synthetic browse answers."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from tests.helpers.browse import (
    CHANNEL_ID,
    VIDEOS_LIST,
    VR_PAGE_1,
    VR_PAGE_2,
    WEB_LAST_PAGE,
    alert_page,
    browse_fixture,
    error_body,
    shorts_page,
    vr_page,
)
from tests.helpers.fake_transport import FakeTransport, json_response, text_response
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.ids import uploads_playlist_id
from utmax.errors import (
    CollectionNotFound,
    CollectionUnavailable,
    InvalidOption,
    InvalidSource,
    IpBlocked,
    UTMaxError,
    YouTubeRequestFailed,
)
from utmax.models import CollectionKind
from utmax.services.collections import CollectionService

PLAYLIST = "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
HANDLE = "@RickAstleyYT"
BROWSE = "/youtubei/v1/browse"
RESOLVE = "/youtubei/v1/navigation/resolve_url"
VR_1 = browse_fixture("browse_android_vr_1")
VR_2 = browse_fixture("browse_android_vr_2")
WEB_1 = browse_fixture("browse_web_1")
WEB_2 = browse_fixture("browse_web_2")


def service(transport: FakeTransport, **options: Any) -> CollectionService:
    return CollectionService(InnerTubeClient(transport), **options)


def sent(transport: FakeTransport) -> list[tuple[str, dict[str, Any]]]:
    """The client name and the body (without its context) of every request."""
    calls = []
    for request in transport.requests:
        body = json.loads(request.body or b"{}")
        calls.append((body.pop("context")["client"]["clientName"], body))
    return calls


def token(page: dict[str, Any]) -> str:
    renderer = page["continuationContents"]["playlistVideoListContinuation"]
    return str(renderer["continuations"][0]["nextContinuationData"]["continuation"])


def first_token() -> str:
    tab = VR_1["contents"]["singleColumnBrowseResultsRenderer"]["tabs"][0]["tabRenderer"]
    renderer = tab["content"]["sectionListRenderer"]["contents"][0]["playlistVideoListRenderer"]
    return str(renderer["continuations"][0]["nextContinuationData"]["continuation"])


def warned(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The warnings a listing logged on utmax.youtube."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "utmax.youtube" and record.levelno >= logging.WARNING
    ]


def test_a_playlist_is_listed_page_by_page() -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(VR_1), json_response(VR_2), json_response(VR_2))
    videos = service(transport).list_videos(VIDEOS_LIST)
    assert [entry.video_id for entry in videos] == VR_PAGE_1 + VR_PAGE_2
    assert [entry.index for entry in videos] == [1, 2, 3, 4, 5]
    assert [entry.duration for entry in videos] == [231.0, 234.0, 248.0, 436.0, 227.0]
    assert (videos.title, videos.source_id, videos.kind, videos.video_count) == (
        "Videos",
        VIDEOS_LIST,
        "all",
        139,
    )
    assert sent(transport) == [
        ("ANDROID_VR", {"browseId": f"VL{VIDEOS_LIST}"}),
        ("ANDROID_VR", {"continuation": first_token()}),
        ("ANDROID_VR", {"continuation": token(VR_2)}),
    ]


def test_limit_stops_the_listing_early() -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(VR_1))
    url = f"https://www.youtube.com/playlist?list={VIDEOS_LIST}"
    videos = service(transport).list_videos(url, limit=2)
    assert [entry.video_id for entry in videos] == VR_PAGE_1[:2]
    assert len(transport.requests) == 1


def test_handles_are_resolved_then_listed_by_kind() -> None:
    transport = FakeTransport()
    transport.add("POST", RESOLVE, json_response(browse_fixture("resolve_handle")))
    transport.add("POST", BROWSE, json_response(VR_1), json_response(VR_2), json_response(VR_2))
    videos = service(transport).list_videos(HANDLE, kind="videos")
    assert (videos.source_id, videos.kind, len(videos)) == (VIDEOS_LIST, "videos", 5)
    assert sent(transport)[:2] == [
        ("ANDROID_VR", {"url": f"https://www.youtube.com/{HANDLE}"}),
        ("ANDROID_VR", {"browseId": f"VL{VIDEOS_LIST}"}),
    ]


def test_web_resolves_what_android_vr_does_not_know() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        RESOLVE,
        json_response(browse_fixture("resolve_unknown")),
        json_response(browse_fixture("resolve_handle")),
    )
    transport.add("POST", BROWSE, json_response(vr_page("aaaaaaaaaaa", count="1 video")))
    videos = service(transport).list_videos("https://www.youtube.com/c/RickAstleyYT")
    assert videos.source_id == f"UU{CHANNEL_ID[2:]}"
    assert [client for client, _ in sent(transport)] == ["ANDROID_VR", "WEB", "ANDROID_VR"]


@pytest.mark.parametrize(
    "source", [CHANNEL_ID, f"https://www.youtube.com/channel/{CHANNEL_ID}/featured"]
)
def test_channel_ids_need_no_resolving(source: str) -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(vr_page("aaaaaaaaaaa", count="1 video")))
    videos = service(transport).list_videos(source)
    assert (videos.source_id, videos.kind) == (f"UU{CHANNEL_ID[2:]}", "all")
    assert transport.urls() == ["https://www.youtube.com/youtubei/v1/browse?prettyPrint=false"]


@pytest.mark.parametrize(
    ("tab", "kind", "expected"),
    [
        ("shorts", None, "shorts"),
        ("videos", None, "videos"),
        ("streams", None, "live"),
        ("shorts", "all", "all"),
        ("videos", "shorts", "shorts"),
    ],
)
def test_a_channel_tab_chooses_the_list_unless_kind_is_given(
    tab: str, kind: CollectionKind | None, expected: CollectionKind
) -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(vr_page("aaaaaaaaaaa", count="1 video")))
    source = f"https://www.youtube.com/channel/{CHANNEL_ID}/{tab}"
    videos = service(transport).list_videos(source, kind=kind)
    assert (videos.kind, videos.source_id) == (expected, uploads_playlist_id(CHANNEL_ID, expected))


def test_web_takes_over_when_android_vr_fails() -> None:
    transport = FakeTransport()
    failed = json_response(error_body(400), status=500)
    transport.add("POST", BROWSE, failed, json_response(WEB_1), json_response(WEB_2))
    videos = service(transport).list_videos(VIDEOS_LIST)
    assert [entry.video_id for entry in videos] == VR_PAGE_1 + WEB_LAST_PAGE
    assert [entry.duration for entry in videos] == [231.0, 234.0, 248.0, 218.0, 219.0, 214.0]
    assert [client for client, _ in sent(transport)] == ["ANDROID_VR", "WEB", "WEB"]


def test_web_restarts_the_listing_when_android_vr_fails_midway() -> None:
    transport = FakeTransport()
    broken = text_response("<html>busy</html>")
    transport.add(
        "POST", BROWSE, json_response(VR_1), broken, json_response(WEB_1), json_response(WEB_2)
    )
    videos = service(transport).list_videos(VIDEOS_LIST)
    assert [entry.video_id for entry in videos] == VR_PAGE_1 + WEB_LAST_PAGE
    assert [entry.index for entry in videos] == [1, 2, 3, 4, 5, 6]
    assert [(client, list(body)) for client, body in sent(transport)] == [
        ("ANDROID_VR", ["browseId"]),
        ("ANDROID_VR", ["continuation"]),
        ("WEB", ["browseId"]),
        ("WEB", ["continuation"]),
    ]


def test_an_unreadable_first_page_falls_back_to_web() -> None:
    transport = FakeTransport()
    unreadable = json_response({"responseContext": {}})
    transport.add("POST", BROWSE, unreadable, json_response(WEB_1), json_response(WEB_2))
    assert len(service(transport).list_videos(VIDEOS_LIST)) == 6


def test_web_lists_shorts_from_the_rich_grid() -> None:
    transport = FakeTransport()
    transport.add("POST", RESOLVE, json_response(browse_fixture("resolve_handle")))
    shorts = json_response(browse_fixture("browse_web_shorts"))
    transport.add("POST", BROWSE, json_response(error_body(400), status=503), shorts)
    videos = service(transport).list_videos(HANDLE, kind="shorts")
    assert (videos.title, videos.video_count, videos.source_id) == (
        "Short videos",
        297,
        f"UUSH{CHANNEL_ID[2:]}",
    )
    assert [(entry.video_id, entry.duration) for entry in videos] == [
        ("E_MGy41IYVw", None),
        ("ihRdK3x3cUY", None),
    ]


def test_empty_playlists_list_nothing() -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(vr_page(count="No videos")))
    videos = service(transport).list_videos(PLAYLIST)
    assert (len(videos), videos.video_count, videos.title) == (0, 0, "A playlist")
    assert len(transport.requests) == 1


def test_missing_playlists_are_not_found() -> None:
    transport = FakeTransport()
    missing = json_response(error_body(400), status=400)
    transport.add("POST", BROWSE, missing, missing)
    with pytest.raises(CollectionNotFound, match="HTTP 400") as caught:
        service(transport).list_videos(PLAYLIST)
    assert caught.value.source == PLAYLIST
    assert [client for client, _ in sent(transport)] == ["ANDROID_VR", "WEB"]


def test_youtube_alerts_explain_unviewable_playlists() -> None:
    transport = FakeTransport()
    alert = json_response(alert_page("This playlist type is unviewable."))
    transport.add("POST", BROWSE, json_response(error_body(400), status=400), alert)
    with pytest.raises(CollectionUnavailable, match="will not list") as caught:
        service(transport).list_videos(PLAYLIST)
    assert (caught.value.source, caught.value.reason) == (
        PLAYLIST,
        "This playlist type is unviewable.",
    )


def test_channels_without_shorts_list_nothing() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        BROWSE,
        json_response(error_body(404), status=404),
        json_response(alert_page("The playlist does not exist.")),
        json_response(vr_page("aaaaaaaaaaa", count="1 video")),
    )
    videos = service(transport).list_videos(CHANNEL_ID, kind="shorts")
    assert (len(videos), videos.video_count, videos.title) == (0, 0, "")
    assert (videos.source_id, videos.kind) == (f"UUSH{CHANNEL_ID[2:]}", "shorts")
    assert [body["browseId"] for _, body in sent(transport)] == [
        f"VLUUSH{CHANNEL_ID[2:]}",
        f"VLUUSH{CHANNEL_ID[2:]}",
        f"VLUU{CHANNEL_ID[2:]}",
    ]


@pytest.mark.parametrize(("kind", "requests"), [("all", 2), ("live", 4)])
def test_channels_without_uploads_are_not_found(kind: CollectionKind, requests: int) -> None:
    transport = FakeTransport()
    missing = json_response(error_body(404), status=404)
    alert = json_response(alert_page("The playlist does not exist."))
    transport.add("POST", BROWSE, missing, alert, missing, alert)
    with pytest.raises(CollectionNotFound, match="could not find") as caught:
        service(transport).list_videos(CHANNEL_ID, kind=kind)
    assert caught.value.source == CHANNEL_ID
    assert len(transport.requests) == requests


def test_unknown_handles_are_not_found_without_browsing() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        RESOLVE,
        json_response(browse_fixture("resolve_unknown")),
        json_response(error_body(404), status=404),
    )
    with pytest.raises(CollectionNotFound, match="knows no channel") as caught:
        service(transport).list_videos("@thishandledoesnotexist20260928x")
    assert caught.value.source == "@thishandledoesnotexist20260928x"
    assert all(RESOLVE in url for url in transport.urls())


def test_resolving_reports_server_errors() -> None:
    transport = FakeTransport()
    transport.add(
        "POST",
        RESOLVE,
        json_response(error_body(400), status=500),
        text_response("<html>busy</html>"),
    )
    with pytest.raises(YouTubeRequestFailed) as caught:
        service(transport).list_videos(HANDLE)
    assert caught.value.status_code == 500


def test_rate_limits_stop_the_listing_at_once() -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response({}, status=429))
    with pytest.raises(IpBlocked):
        service(transport).list_videos(PLAYLIST)
    assert len(transport.requests) == 1


def test_the_page_cap_stops_endless_listings(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeTransport()
    pages = [vr_page(f"{letter * 11}", token=f"t{n}") for n, letter in enumerate("abc", 1)]
    transport.add("POST", BROWSE, *(json_response(page) for page in pages))
    with caplog.at_level(logging.WARNING, logger="utmax.youtube"):
        videos = service(transport, max_pages=2).list_videos(PLAYLIST)
    assert [entry.video_id for entry in videos] == ["a" * 11, "b" * 11]
    assert "stopped listing" in caplog.text


def test_web_lists_at_most_100_shorts_and_the_listing_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Live on 2026-09-29: WEB answers a channel's Shorts with 100 items and no continuation of
    # any shape, whatever the header counts; ANDROID_VR lists all 297.
    first_hundred = [f"short{number:06d}" for number in range(100)]
    transport = FakeTransport()
    transport.add("POST", RESOLVE, json_response(browse_fixture("resolve_handle")))
    web = json_response(shorts_page(*first_hundred, count="297 videos"))
    transport.add("POST", BROWSE, json_response(error_body(400), status=503), web)
    with caplog.at_level(logging.WARNING, logger="utmax.youtube"):
        videos = service(transport).list_videos(HANDLE, kind="shorts")
    assert [entry.video_id for entry in videos] == first_hundred
    assert (videos.video_count, videos.source_id) == (297, f"UUSH{CHANNEL_ID[2:]}")
    assert [client for client, _ in sent(transport)] == ["ANDROID_VR", "ANDROID_VR", "WEB"]
    assert warned(caplog) == [
        f"InnerTube client WEB, playlist UUSH{CHANNEL_ID[2:]}: listed 100 of the 297 videos "
        "YouTube counts; the list may be incomplete"
    ]


def test_a_continuation_page_without_items_ends_the_listing_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = FakeTransport()
    nothing = json_response({"responseContext": {}})  # valid JSON: no items, no token
    transport.add("POST", BROWSE, json_response(VR_1), nothing)
    with caplog.at_level(logging.WARNING, logger="utmax.youtube"):
        videos = service(transport).list_videos(VIDEOS_LIST)
    assert [entry.video_id for entry in videos] == VR_PAGE_1
    assert [client for client, _ in sent(transport)] == ["ANDROID_VR", "ANDROID_VR"]
    assert warned(caplog) == [
        f"InnerTube client ANDROID_VR, playlist {VIDEOS_LIST}: listed 3 of the 139 videos "
        "YouTube counts; the list may be incomplete"
    ]


def test_complete_listings_stay_silent_although_videos_are_hidden(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # ANDROID_VR lists a private video as an unplayable item and counts it: 3 items, "3 videos".
    hidden = {"playlistVideoRenderer": {"videoId": "c" * 11, "isPlayable": False}}
    second = vr_page("b" * 11)
    second["continuationContents"]["playlistVideoListContinuation"]["contents"].append(hidden)
    transport = FakeTransport()
    first = vr_page("a" * 11, token="t1", count="3 videos")
    transport.add("POST", BROWSE, json_response(first), json_response(second))
    with caplog.at_level(logging.WARNING, logger="utmax.youtube"):
        videos = service(transport).list_videos(PLAYLIST)
    assert [entry.video_id for entry in videos] == ["a" * 11, "b" * 11]
    assert videos.video_count == 3
    assert warned(caplog) == []


def test_a_limit_is_not_a_shortfall(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeTransport()
    transport.add("POST", BROWSE, json_response(VR_1))
    with caplog.at_level(logging.WARNING, logger="utmax.youtube"):
        videos = service(transport).list_videos(VIDEOS_LIST, limit=2)
    assert [entry.video_id for entry in videos] == VR_PAGE_1[:2]
    assert warned(caplog) == []


def test_a_listing_without_a_video_count_stays_silent(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeTransport()
    pages = [vr_page("a" * 11, token="t1"), vr_page()]  # no header, so no count; then nothing
    transport.add("POST", BROWSE, *(json_response(page) for page in pages))
    with caplog.at_level(logging.WARNING, logger="utmax.youtube"):
        videos = service(transport).list_videos(PLAYLIST)
    assert (len(videos), videos.video_count) == (1, None)
    assert warned(caplog) == []


def test_the_page_cap_is_the_only_warning_of_a_capped_listing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = FakeTransport()
    pages = [vr_page("a" * 11, token="t1", count="30 videos"), vr_page("b" * 11, token="t2")]
    transport.add("POST", BROWSE, *(json_response(page) for page in pages))
    with caplog.at_level(logging.WARNING, logger="utmax.youtube"):
        videos = service(transport, max_pages=2).list_videos(PLAYLIST)
    assert len(videos) == 2
    (message,) = warned(caplog)
    assert message.startswith("stopped listing")


@pytest.mark.parametrize(
    ("source", "options", "error"),
    [
        (PLAYLIST, {"kind": "music"}, InvalidOption),
        (PLAYLIST, {"limit": 0}, InvalidOption),
        (PLAYLIST, {"limit": True}, InvalidOption),
        (PLAYLIST, {"limit": 2.5}, InvalidOption),
        (PLAYLIST, {"kind": "videos"}, InvalidOption),
        ("https://youtu.be/dQw4w9WgXcQ", {}, InvalidSource),
        ("RDdQw4w9WgXcQ", {}, CollectionUnavailable),
    ],
)
def test_bad_arguments_fail_before_any_request(
    source: str, options: dict[str, Any], error: type[UTMaxError]
) -> None:
    transport = FakeTransport()
    with pytest.raises(error):
        service(transport).list_videos(source, **options)
    assert transport.requests == []
