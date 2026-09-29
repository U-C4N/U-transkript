"""Tests for reading browse and resolve_url answers (recorded and synthetic)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.browse import (
    CHANNEL_ID,
    VR_PAGE_1,
    VR_PAGE_2,
    WEB_LAST_PAGE,
    alert_page,
    browse_fixture,
    lockup,
    vr_page,
    web_page,
)
from utmax.core.browse import BrowsePage, alert_error, parse_browse_page, resolved_channel_id
from utmax.errors import CollectionNotFound, CollectionUnavailable
from utmax.models import VideoEntry


def test_android_vr_first_page() -> None:
    page = parse_browse_page(browse_fixture("browse_android_vr_1"))
    assert (page.title, page.video_count, page.items, page.alerts) == ("Videos", 139, 3, ())
    assert [video.video_id for video in page.videos] == VR_PAGE_1
    assert page.videos[0] == VideoEntry(
        video_id="PXC_PYeB6F8",
        title="Rick Astley - Angels On My Side (Live at The O2, London, April 2026)",
        duration=231.0,
        channel="Rick Astley",
        channel_id=CHANNEL_ID,
        index=0,
    )
    assert [video.duration for video in page.videos] == [231.0, 234.0, 248.0]
    assert page.continuation is not None
    assert page.continuation.startswith("4qmFsgJUEhxW")


def test_android_vr_continuation_page() -> None:
    first = parse_browse_page(browse_fixture("browse_android_vr_1"))
    page = parse_browse_page(browse_fixture("browse_android_vr_2"))
    assert (page.title, page.video_count, page.items) == ("", None, 2)
    assert [video.video_id for video in page.videos] == VR_PAGE_2
    assert [video.duration for video in page.videos] == [436.0, 227.0]
    assert page.continuation not in (None, first.continuation)


def test_web_first_page() -> None:
    page = parse_browse_page(browse_fixture("browse_web_1"))
    assert (page.title, page.video_count, page.items) == ("Videos", 139, 3)
    assert [video.video_id for video in page.videos] == VR_PAGE_1
    assert [video.duration for video in page.videos] == [231.0, 234.0, 248.0]
    assert {(video.channel, video.channel_id) for video in page.videos} == {
        ("Rick Astley", CHANNEL_ID)
    }
    assert page.videos[1].title == "Rick Astley - Dance (Live at The O2, London, April 2026)"
    assert page.continuation is not None
    assert page.continuation.startswith("4qmFsgJxEhxW")


def test_web_last_page_has_no_continuation() -> None:
    page = parse_browse_page(browse_fixture("browse_web_2"))
    assert [video.video_id for video in page.videos] == WEB_LAST_PAGE
    assert [video.duration for video in page.videos] == [218.0, 219.0, 214.0]
    assert page.continuation is None


def test_web_shorts_take_their_channel_from_the_header() -> None:
    page = parse_browse_page(browse_fixture("browse_web_shorts"))
    assert (page.title, page.video_count, page.items) == ("Short videos", 297, 2)
    assert [video.video_id for video in page.videos] == ["E_MGy41IYVw", "ihRdK3x3cUY"]
    assert page.videos[0].title.startswith("38 years on, and the music video still hits")
    assert page.videos[1].title.startswith("A message from Rick")
    assert {(v.duration, v.channel, v.channel_id) for v in page.videos} == {
        (None, "Rick Astley", CHANNEL_ID)
    }


def test_only_a_first_page_names_the_playlist_owner() -> None:
    whole = browse_fixture("browse_web_shorts")
    first = parse_browse_page(whole)
    assert (first.owner_name, first.owner_id) == ("Rick Astley", CHANNEL_ID)
    # Shorts never name a channel and continuation pages have no header: a listing fills in.
    later = parse_browse_page({key: value for key, value in whole.items() if key != "header"})
    assert (later.owner_name, later.owner_id) == ("", "")
    assert {(video.channel, video.channel_id) for video in later.videos} == {("", "")}


def test_unplayable_and_foreign_items_are_counted_but_skipped() -> None:
    hidden = {"playlistVideoRenderer": {"videoId": "aaaaaaaaaaa", "isPlayable": False}}
    broken = {"playlistVideoRenderer": {"videoId": "too-short"}}
    playlist = {"lockupViewModel": {"contentId": "PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"}}
    short = {"shortsLockupViewModel": {"onTap": {}}}
    page = parse_browse_page(
        web_page(hidden, broken, playlist, short, lockup("bbbbbbbbbbb", title="Kept"))
    )
    assert page.items == 5
    assert [(video.video_id, video.title) for video in page.videos] == [("bbbbbbbbbbb", "Kept")]


def test_items_name_their_own_channel_before_the_header_owner() -> None:
    owner = {"runs": [{"text": "Owner", "navigationEndpoint": {}}]}
    header = {"playlistHeaderRenderer": {"title": {"simpleText": "Mixed"}, "ownerText": owner}}
    other = "UC" + "o" * 22
    page = parse_browse_page(web_page(lockup("aaaaaaaaaaa", channel_id=other), header=header))
    (video,) = page.videos
    assert (video.channel, video.channel_id) == ("Some Channel", other)
    page = parse_browse_page(web_page(lockup("aaaaaaaaaaa"), header=header))
    assert (page.videos[0].channel, page.videos[0].channel_id) == ("Owner", "")


def test_older_web_pages_continue_through_a_continuation_item_renderer() -> None:
    renderer = {
        "continuationItemRenderer": {
            "continuationEndpoint": {"continuationCommand": {"token": "old-token"}}
        }
    }
    action = {"appendContinuationItemsAction": {"continuationItems": [lockup("aaaaaaaaaaa")]}}
    page = parse_browse_page({"onResponseReceivedActions": [action, renderer]})
    assert (page.items, page.continuation) == (1, "old-token")


def test_the_first_continuation_token_wins() -> None:
    def renderer(token: str) -> dict[str, Any]:
        command = {"continuationCommand": {"token": token}}
        return {"continuationItemRenderer": {"continuationEndpoint": command}}

    empty = {"nextContinuationData": {"continuation": ""}}
    page = parse_browse_page({"contents": [empty, renderer("first"), renderer("second")]})
    assert page.continuation == "first"


def test_the_first_link_to_a_channel_names_a_lockups_channel() -> None:
    channel_id = "UC" + "c" * 22
    item = lockup("aaaaaaaaaaa", channel_id=channel_id)
    meta = item["lockupViewModel"]["metadata"]["lockupMetadataViewModel"]["metadata"]
    parts = meta["contentMetadataViewModel"]["metadataRows"][0]["metadataParts"]
    to_playlist = {"onTap": {"innertubeCommand": {"browseEndpoint": {"browseId": "VLPLx"}}}}
    parts.insert(0, {"text": {"content": "A playlist", "commandRuns": [to_playlist, {}]}})
    (video,) = parse_browse_page(web_page(item)).videos
    assert (video.channel, video.channel_id) == ("Some Channel", channel_id)


def test_web_playlist_pages_use_the_page_header() -> None:
    rows = [
        {"metadataParts": [{"avatarStack": {}}]},
        {
            "metadataParts": [
                {"text": {"content": "Playlist"}},
                {"text": {"content": "10 videos"}},
                {"text": {"content": "248,980 views"}},
            ]
        },
    ]
    view = {"metadata": {"contentMetadataViewModel": {"metadataRows": rows}}}
    header = {
        "pageHeaderRenderer": {
            "pageTitle": "RickAstley - Greatest Hits",
            "content": {"pageHeaderViewModel": view},
        }
    }
    page = parse_browse_page(web_page(lockup("aaaaaaaaaaa"), header=header))
    assert (page.title, page.video_count) == ("RickAstley - Greatest Hits", 10)


def test_the_title_falls_back_to_the_playlist_metadata() -> None:
    data = web_page(lockup("aaaaaaaaaaa"))
    data["metadata"] = {"playlistMetadataRenderer": {"title": "Uploads from jawed"}}
    assert parse_browse_page(data).title == "Uploads from jawed"


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("139 videos", 139),
        ("1 video", 1),
        ("1,234 videos", 1234),
        ("No videos", 0),
        ("", None),
        ("many videos", None),
        (", videos", None),
        pytest.param("9" * 5000 + " videos", None, id="5000 digits"),
    ],
)
def test_video_counts(text: str, count: int | None) -> None:
    assert parse_browse_page(vr_page(count=text or " ")).video_count == count


@pytest.mark.parametrize(
    ("badge", "seconds"),
    [("3:51", 231.0), ("0:05", 5.0), ("1:02:03", 3723.0), ("LIVE", None), ("SHORTS", None)],
)
def test_durations_come_from_the_thumbnail_badge(badge: str, seconds: float | None) -> None:
    (video,) = parse_browse_page(web_page(lockup("aaaaaaaaaaa", badge=badge))).videos
    assert video.duration == seconds


@pytest.mark.parametrize(
    ("length", "seconds"), [("231", 231.0), (231, 231.0), ("\xb2", None), ("2.5", None)]
)
def test_android_vr_lengths_are_whole_seconds(length: object, seconds: float | None) -> None:
    item = {"playlistVideoRenderer": {"videoId": "aaaaaaaaaaa", "lengthSeconds": length}}
    (video,) = parse_browse_page({"contents": [item]}).videos
    assert video.duration == seconds


def test_alert_only_answers_become_errors() -> None:
    mix = parse_browse_page(alert_page("This playlist type is unviewable."))
    assert (mix.items, mix.alerts) == (0, ("This playlist type is unviewable.",))
    unavailable = alert_error(mix, source="PLx")
    assert isinstance(unavailable, CollectionUnavailable)
    assert (unavailable.source, unavailable.reason) == ("PLx", "This playlist type is unviewable.")
    missing = alert_error(
        parse_browse_page(alert_page("The playlist does not exist.")), source="@x"
    )
    assert isinstance(missing, CollectionNotFound)
    assert missing.source == "@x"
    assert "The playlist does not exist." in str(missing)


def test_alerts_with_buttons_are_read_too() -> None:
    data = {"alerts": [{"alertWithButtonRenderer": {"text": {"simpleText": "Hidden videos."}}}]}
    assert parse_browse_page(data).alerts == ("Hidden videos.",)


def test_resolved_channel_ids() -> None:
    assert resolved_channel_id(browse_fixture("resolve_handle")) == CHANNEL_ID
    assert resolved_channel_id(browse_fixture("resolve_unknown")) is None
    elsewhere = {"endpoint": {"browseEndpoint": {"browseId": "VLPLFgquLnL59alCl_2TQvOiD5Vgm1"}}}
    assert resolved_channel_id(elsewhere) is None
    assert resolved_channel_id({}) is None


@pytest.mark.parametrize(
    "data",
    [{}, {"contents": "text"}, {"contents": [1, None, [{}]]}, {"header": [], "alerts": "x"}],
)
def test_unexpected_shapes_are_ignored(data: dict[str, Any]) -> None:
    assert parse_browse_page(data) == BrowsePage()
