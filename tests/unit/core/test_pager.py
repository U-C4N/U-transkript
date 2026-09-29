"""Tests for the Pager, which decides when a listing is complete."""

from __future__ import annotations

import json

import pytest

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


def test_items_sum_every_list_item_of_every_page() -> None:
    pager = Pager()
    assert pager.items == 0
    assert pager.add(page("a", token="t1", items=20)) == "t1"  # 19 items were skipped
    assert pager.add(page("b", "a", token="t2")) == "t2"  # a repeated video is an item too
    assert pager.add(page("c")) is None  # the last page counts as well
    assert pager.items == 23
    assert len(pager.entries) == 3


@pytest.mark.parametrize(
    ("count", "short"), [(None, False), (2, False), (3, False), (4, True), (139, True)]
)
def test_a_listing_that_ended_on_its_own_is_short_of_a_larger_count(
    count: int | None, short: bool
) -> None:
    pager = Pager()
    assert pager.add(page("a", "b", token="t1")) == "t1"
    assert pager.add(page("c")) is None
    assert pager.ended_short(count) is short


@pytest.mark.parametrize(
    "last",
    [page("c"), page(token="t2"), page("c", token="t1")],
    ids=["no continuation", "no items", "repeated token"],
)
def test_every_way_a_listing_ends_on_its_own_can_leave_it_short(last: BrowsePage) -> None:
    pager = Pager()
    assert pager.add(page("a", "b", token="t1")) == "t1"
    assert pager.add(last) is None
    assert pager.ended_short(139)


def test_a_limit_or_the_page_cap_is_not_a_short_listing() -> None:
    limited = Pager(limit=2)
    assert limited.add(page("a", "b", token="t1")) is None
    assert not limited.ended_short(139)
    capped = Pager(max_pages=2)
    assert capped.add(page("a", token="t1")) == "t1"
    assert capped.add(page("b", token="t2")) is None
    assert capped.truncated
    assert not capped.ended_short(139)
