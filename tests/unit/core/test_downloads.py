"""Tests for chunk, resume-state and rate arithmetic."""

from __future__ import annotations

from itertools import pairwise

import pytest

from utmax.core.downloads import (
    MIB,
    Chunk,
    PartState,
    RateMeter,
    Throttle,
    content_range_total,
    expires_soon,
    plan_chunks,
    range_header,
)

STATE = PartState("dQw4w9WgXcQ", 137, 80_911_999, "1766957926174250", 8 * MIB, frozenset({0, 2}))


@pytest.mark.parametrize(
    ("size", "chunk_size", "expected"),
    [
        (0, 8, ()),
        (1, 8, (Chunk(0, 0, 1),)),
        (15, 8, (Chunk(0, 0, 15),)),
        (16, 8, (Chunk(0, 0, 8), Chunk(1, 8, 16))),
        (17, 8, (Chunk(0, 0, 8), Chunk(1, 8, 16), Chunk(2, 16, 17))),
    ],
)
def test_plan_chunks(size: int, chunk_size: int, expected: tuple[Chunk, ...]) -> None:
    assert plan_chunks(size, chunk_size) == expected


def test_chunks_tile_large_streams_exactly() -> None:
    chunks = plan_chunks(80_911_999, 8 * MIB)
    assert len(chunks) == 10
    assert chunks[0] == Chunk(0, 0, 8 * MIB)
    assert chunks[-1].end == 80_911_999
    assert all(first.end == second.start for first, second in pairwise(chunks))
    assert sum(chunk.size for chunk in chunks) == 80_911_999


def test_range_header() -> None:
    assert range_header(0, 1) == "bytes=0-0"
    assert range_header(8, 16) == "bytes=8-15"


@pytest.mark.parametrize(
    ("value", "total"),
    [
        ("bytes 0-0/3449447", 3449447),
        ("bytes */500", 500),
        ("BYTES 1-2/3", 3),
        ("bytes 0-0/*", None),
        ("items 0-0/5", None),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_content_range_total(value: str | None, total: int | None) -> None:
    assert content_range_total(value) == total


def test_expires_soon() -> None:
    assert expires_soon(1000, 701)
    assert not expires_soon(1000, 700)
    assert not expires_soon(None, 10.0**12)
    assert expires_soon(1000, 950, margin=60)


def test_part_state_round_trips_as_compact_json() -> None:
    text = STATE.to_json()
    assert text == (
        '{"version":1,"video_id":"dQw4w9WgXcQ","itag":137,"content_length":80911999,'
        '"last_modified":"1766957926174250","chunk_size":8388608,"completed":[0,2]}'
    )
    assert PartState.from_json(text) == STATE


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json",
        "[]",
        '{"version": 2}',
        '{"version":1,"video_id":"v","itag":"x","content_length":1,"last_modified":"",'
        '"chunk_size":1,"completed":[]}',
        '{"version":1,"video_id":"v","itag":1,"content_length":1,"last_modified":"",'
        '"chunk_size":1}',
        '{"version":1,"video_id":"v","itag":1,"content_length":1,"last_modified":"",'
        '"chunk_size":1,"completed":5}',
    ],
)
def test_damaged_state_files_are_ignored(text: str) -> None:
    assert PartState.from_json(text) is None


def test_states_match_only_for_the_same_stream_and_chunking() -> None:
    assert STATE.matches(PartState("dQw4w9WgXcQ", 137, 80_911_999, "1766957926174250", 8 * MIB))
    for other in (
        PartState("otherVideo1", 137, 80_911_999, "1766957926174250", 8 * MIB),
        PartState("dQw4w9WgXcQ", 136, 80_911_999, "1766957926174250", 8 * MIB),
        PartState("dQw4w9WgXcQ", 137, 80_911_998, "1766957926174250", 8 * MIB),
        PartState("dQw4w9WgXcQ", 137, 80_911_999, "1766957926174251", 8 * MIB),
        PartState("dQw4w9WgXcQ", 137, 80_911_999, "1766957926174250", 4 * MIB),
    ):
        assert not STATE.matches(other)


def test_rate_meter_measures_speed_and_time_left() -> None:
    meter = RateMeter(window=5.0)
    assert meter.update(0.0, 0, 1000) == (None, None)
    assert meter.update(1.0, 100, 1000) == (100.0, 9.0)
    assert meter.update(2.0, 250, 1000) == (125.0, 6.0)
    assert meter.update(3.0, 300, None) == (100.0, None)


def test_rate_meter_forgets_samples_older_than_its_window() -> None:
    meter = RateMeter(window=2.0)
    meter.update(0.0, 0, None)
    meter.update(1.0, 1000, None)
    meter.update(2.0, 1100, None)
    assert meter.update(3.0, 1200, None) == (100.0, None)


def test_throttle_lets_one_event_through_per_interval() -> None:
    throttle = Throttle(0.25)
    assert throttle.ready(10.0)
    assert not throttle.ready(10.1)
    assert throttle.ready(10.25)
    assert not throttle.ready(10.3)
    assert throttle.ready(10.3, force=True)
