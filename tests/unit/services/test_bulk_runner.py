"""Tests for the bulk runner: order, concurrency, skips, the circuit breaker and Ctrl-C."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from utmax.errors import (
    InvalidOption,
    InvalidVideoId,
    IpBlocked,
    ProviderAuthError,
    VideoUnavailable,
)
from utmax.models import BulkResult, VideoEntry
from utmax.services.bulk import BulkItem, bulk_items, check_concurrency, run_bulk

IDS = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"]


def upper(item: BulkItem) -> tuple[str, Path | None]:
    return item.video_id.upper(), None


def test_results_keep_the_input_order_and_progress_the_finishing_order() -> None:
    second_reported = threading.Event()
    seen: list[BulkResult[str]] = []

    def work(item: BulkItem) -> tuple[str, Path | None]:
        if item.video_id == IDS[0]:
            assert second_reported.wait(5)
        return upper(item)

    def progress(result: BulkResult[str]) -> None:
        seen.append(result)
        if result.video_id == IDS[1]:
            second_reported.set()

    report = run_bulk(bulk_items(IDS[:2]), work, concurrency=2, progress=progress)
    assert [(result.video_id, result.status) for result in report] == [
        (IDS[0], "ok"),
        (IDS[1], "ok"),
    ]
    assert [result.value for result in report] == [IDS[0].upper(), IDS[1].upper()]
    assert [result.video_id for result in seen] == [IDS[1], IDS[0]]


def test_items_that_need_no_work_are_decided_first() -> None:
    calls: list[str] = []

    def work(item: BulkItem) -> tuple[str, Path | None]:
        calls.append(item.video_id)
        if item.video_id == IDS[2]:
            raise VideoUnavailable("gone", video_id=item.video_id)
        return "value", Path(f"{item.video_id}.srt")

    def existing(item: BulkItem) -> Path | None:
        return Path("old.srt") if item.video_id == IDS[1] else None

    seen: list[BulkResult[str]] = []
    videos = [IDS[0], "not a video", IDS[1], f"https://youtu.be/{IDS[0]}", IDS[2]]
    report = run_bulk(
        bulk_items(videos), work, concurrency=1, existing=existing, progress=seen.append
    )
    assert [(result.video_id, result.status) for result in report] == [
        (IDS[0], "ok"),
        ("not a video", "failed"),
        (IDS[1], "skipped"),
        (IDS[0], "skipped"),
        (IDS[2], "failed"),
    ]
    assert (report[0].value, report[0].path) == ("value", Path(f"{IDS[0]}.srt"))
    assert isinstance(report[1].error, InvalidVideoId)
    assert (report[2].path, report[3].path) == (Path("old.srt"), None)
    assert isinstance(report[4].error, VideoUnavailable)
    assert sorted(calls) == [IDS[0], IDS[2]]
    assert [result.video_id for result in seen[:3]] == ["not a video", IDS[1], IDS[0]]
    assert len(seen) == 5


def test_no_more_than_concurrency_videos_run_at_once() -> None:
    lock = threading.Lock()
    active = peak = 0

    def work(item: BulkItem) -> tuple[None, Path | None]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return None, None

    report = run_bulk(bulk_items([letter * 11 for letter in "abcdefgh"]), work, concurrency=3)
    assert len(report.ok) == 8
    assert 1 <= peak <= 3


def test_a_block_stops_the_run(caplog: pytest.LogCaptureFixture) -> None:
    def work(item: BulkItem) -> tuple[str, Path | None]:
        if item.video_id == IDS[1]:
            raise IpBlocked("HTTP 429", video_id=item.video_id)
        return upper(item)

    seen: list[BulkResult[str]] = []
    with caplog.at_level(logging.WARNING, logger="utmax.bulk"):
        report = run_bulk(bulk_items(IDS), work, concurrency=1, progress=seen.append)
    statuses = [result.status for result in report]
    assert statuses == ["ok", "failed", "not_attempted", "not_attempted"]
    assert len(seen) == 4
    assert "not attempted" in caplog.text
    with pytest.raises(IpBlocked):
        report.raise_for_errors()


def test_callers_choose_what_stops_the_run() -> None:
    def work(item: BulkItem) -> tuple[str, Path | None]:
        raise ProviderAuthError("The API key was rejected.", provider="fake")

    stopped = run_bulk(bulk_items(IDS[:3]), work, concurrency=1, breaker=(ProviderAuthError,))
    assert [result.status for result in stopped] == ["failed", "not_attempted", "not_attempted"]
    carried_on = run_bulk(bulk_items(IDS[:3]), work, concurrency=1)
    assert [result.status for result in carried_on] == ["failed", "failed", "failed"]


@pytest.mark.parametrize("error", [KeyboardInterrupt, ValueError])
def test_ctrl_c_or_a_progress_error_stops_the_run(error: type[BaseException]) -> None:
    stop = threading.Event()
    calls: list[str] = []

    def work(item: BulkItem) -> tuple[str, Path | None]:
        calls.append(item.video_id)
        return upper(item)

    def progress(result: BulkResult[str]) -> None:
        raise error

    with pytest.raises(error):
        run_bulk(bulk_items(IDS), work, concurrency=1, progress=progress, stop=stop)
    assert stop.is_set()
    assert 1 <= len(calls) <= 2


def test_nothing_to_do() -> None:
    assert len(run_bulk([], upper, concurrency=4)) == 0
    report = run_bulk(bulk_items(["nope"]), upper, concurrency=4)
    assert [result.status for result in report] == ["failed"]


def test_bulk_items_read_ids_urls_and_listing_entries() -> None:
    entry = VideoEntry("eeeeeeeeeee", "E", 60.0, "Channel", "UC" + "x" * 22, 7)
    items = bulk_items(iter([f"https://youtu.be/{IDS[1]}", entry, " bad "]))
    assert [(item.position, item.video_id, item.index) for item in items] == [
        (1, IDS[1], 1),
        (2, "eeeeeeeeeee", 7),
        (3, "bad", 3),
    ]
    assert items[1].video is entry
    assert (items[0].error, type(items[2].error)) == (None, InvalidVideoId)


@pytest.mark.parametrize("videos", ["dQw4w9WgXcQ", VideoEntry("eeeeeeeeeee", "E", None, "", "", 1)])
def test_one_video_is_not_a_list(videos: Any) -> None:
    with pytest.raises(InvalidOption, match="must be a list"):
        bulk_items(videos)


@pytest.mark.parametrize("value", [0, 17, -1, True, 2.0])
def test_concurrency_is_between_1_and_16(value: Any) -> None:
    with pytest.raises(InvalidOption, match="concurrency must be between 1 and 16"):
        check_concurrency(value)
    check_concurrency(1)
    check_concurrency(16)
