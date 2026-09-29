"""Tests for the Pager, which decides when a listing is complete."""

from __future__ import annotations

import json

from tests.helpers.browse import CHANNEL_ID, browse_fixture
from utmax.core.browse import MAX_PAGES, BrowsePage, Pager, parse_browse_page
from utmax.models import VideoEntry


def page(*video_ids: str, token: str | None = None, items: int | None = None) -> BrowsePage:
    videos = tuple(
        VideoEntry(v, f"Video {v}", 60.0, "Channel", "UC" + "x" * 22, 0) for v in video_ids
    )
    return BrowsePage(videos, len(videos) if items is None else items, token)


def ids(pager: Pager) -> list[tuple[str, int]]:
    return [(entry.video_id, entry.index) for entry in pager.entries]


def test_videos_are_numbered_across_pages_and_repeats_dropped() -> None:
    pager = Pager()
    assert pager.add(page("a", "b", token="t1")) == "t1"
    assert pager.add(page("b", "c", token="t2")) == "t2"
    assert pager.add(page("d")) is None
    assert ids(pager) == [("a", 1), ("b", 2), ("c", 3), ("d", 4)]
    assert pager.entries[2].title == "Video c"
    assert not pager.truncated


def test_the_limit_stops_in_the_middle_of_a_page() -> None:
    pager = Pager(limit=3)
    assert pager.add(page("a", "b", token="t1")) == "t1"
    assert pager.add(page("c", "d", "e", token="t2")) is None
    assert ids(pager) == [("a", 1), ("b", 2), ("c", 3)]


def test_a_full_first_page_needs_no_second_request() -> None:
    pager = Pager(limit=2)
    assert pager.add(page("a", "b", token="t1")) is None
    assert ids(pager) == [("a", 1), ("b", 2)]


def test_a_repeated_token_ends_the_listing() -> None:
    pager = Pager()
    assert pager.add(page("a", token="t1")) == "t1"
    assert pager.add(page("b", token="t1")) is None
    assert ids(pager) == [("a", 1), ("b", 2)]


def test_a_page_without_items_ends_the_listing() -> None:
    pager = Pager()
    assert pager.add(page("a", token="t1")) == "t1"
    assert pager.add(page(token="t2")) is None
    assert ids(pager) == [("a", 1)]


def test_pages_of_skipped_items_do_not_end_the_listing() -> None:
    pager = Pager()
    assert pager.add(page(token="t1", items=20)) == "t1"
    assert pager.add(page("a")) is None
    assert ids(pager) == [("a", 1)]


def test_the_page_cap_truncates_endless_listings() -> None:
    pager = Pager(max_pages=3)
    assert pager.add(page("a", token="t1")) == "t1"
    assert pager.add(page("b", token="t2")) == "t2"
    assert pager.add(page("c", token="t3")) is None
    assert pager.truncated
    assert ids(pager) == [("a", 1), ("b", 2), ("c", 3)]
    assert MAX_PAGES == 1000


def test_videos_that_name_no_channel_get_the_owner_of_the_first_page() -> None:
    whole = browse_fixture("browse_web_shorts")
    # The next page of Shorts: no header (as on every continuation page), other videos.
    text = json.dumps({key: value for key, value in whole.items() if key != "header"})
    text = text.replace("E_MGy41IYVw", "aaaaaaaaaaa").replace("ihRdK3x3cUY", "bbbbbbbbbbb")
    pager = Pager()
    pager.add(parse_browse_page(whole))
    pager.add(parse_browse_page(json.loads(text)))
    assert ids(pager) == [
        ("E_MGy41IYVw", 1),
        ("ihRdK3x3cUY", 2),
        ("aaaaaaaaaaa", 3),
        ("bbbbbbbbbbb", 4),
    ]
    assert {(entry.channel, entry.channel_id) for entry in pager.entries} == {
        ("Rick Astley", CHANNEL_ID)
    }


def test_videos_keep_the_channel_they_name() -> None:
    other, owner = "UC" + "x" * 22, "UC" + "o" * 22
    named = VideoEntry("a", "A", 60.0, "Other", other, 0)
    unnamed = VideoEntry("b", "B", None, "", "", 0)
    pager = Pager()
    pager.add(BrowsePage((named,), 1, "t1", owner_name="Owner", owner_id=owner))
    pager.add(BrowsePage((unnamed,), 1))
    assert [(entry.channel, entry.channel_id) for entry in pager.entries] == [
        ("Other", other),
        ("Owner", owner),
    ]
