"""Tests for the parallel, resumable downloader: the normal path (fake media, real files)."""

from __future__ import annotations

import json
from itertools import count
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from tests.helpers.fake_media import FakeMedia, media_stream, pattern
from utmax.adapters.downloader import Downloader, Job, ProgressReporter
from utmax.models import Progress

CHUNK = 1000


def downloader(media: FakeMedia, **options: Any) -> Downloader:
    options.setdefault("chunk_size", CHUNK)
    options.setdefault("sleep", lambda _: None)
    return Downloader(media.stream, **options)


def state_of(job: Job) -> dict[str, Any]:
    return json.loads(job.state_path.read_text(encoding="utf-8"))


def test_a_stream_is_downloaded_in_ranges_into_its_part_file(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(4500)
    job = Job(media_stream(137, media.add("video", data), len(data)), tmp_path / "out" / "v.part")
    assert downloader(media, connections=3).run([job], video_id="v") is False
    assert job.part.read_bytes() == data
    assert sorted(media.ranges("video")) == [
        "bytes=0-999",
        "bytes=1000-1999",
        "bytes=2000-2999",
        "bytes=3000-3999",
        "bytes=4000-4499",
    ]
    assert state_of(job)["completed"] == [0, 1, 2, 3, 4]
    assert all(body.closed for body in media.bodies)


def test_small_streams_take_one_request(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(1999)
    stream = media_stream(140, media.add("audio", data), len(data), audio=True)
    job = Job(stream, tmp_path / "a.part")
    downloader(media).run([job], video_id="v")
    assert media.ranges("audio") == ["bytes=0-1998"]
    assert job.part.read_bytes() == data


def test_streams_share_one_queue_in_offset_order(tmp_path: Path) -> None:
    media = FakeMedia()
    video, audio = pattern(3000), pattern(2000, seed=3)
    jobs = [
        Job(media_stream(137, media.add("video", video), 3000), tmp_path / "v.part"),
        Job(media_stream(140, media.add("audio", audio), 2000, audio=True), tmp_path / "a.part"),
    ]
    downloader(media, connections=1).run(jobs, video_id="v")
    assert [(urlsplit(r.url).path, r.headers["Range"]) for r in media.requests] == [
        ("/video", "bytes=0-999"),
        ("/audio", "bytes=0-999"),
        ("/video", "bytes=1000-1999"),
        ("/audio", "bytes=1000-1999"),
        ("/video", "bytes=2000-2999"),
    ]
    assert (jobs[0].part.read_bytes(), jobs[1].part.read_bytes()) == (video, audio)


def test_many_connections_write_the_right_bytes(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(50_000)
    job = Job(media_stream(137, media.add("video", data), len(data)), tmp_path / "v.part")
    downloader(media, connections=8).run([job], video_id="v")
    assert job.part.read_bytes() == data
    assert len(media.requests) == 50


def test_unknown_sizes_are_probed_with_a_one_byte_request(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(2500)
    job = Job(media_stream(137, media.add("video", data), None), tmp_path / "v.part")
    downloader(media).run([job], video_id="v")
    ranges = media.ranges("video")
    assert ranges[0] == "bytes=0-0"
    assert sorted(ranges[1:]) == ["bytes=0-999", "bytes=1000-1999", "bytes=2000-2499"]
    assert job.part.read_bytes() == data


def test_media_requests_name_the_client_and_ask_for_raw_bytes(tmp_path: Path) -> None:
    media = FakeMedia()
    job = Job(media_stream(137, media.add("video", pattern(10)), 10), tmp_path / "v.part")
    downloader(media).run([job], video_id="v")
    (request,) = media.requests
    assert request.headers["User-Agent"] == "test-agent"
    assert request.headers["Accept-Encoding"] == "identity"


def test_progress_reports_are_monotonic_throttled_and_complete(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(20_000)
    job = Job(media_stream(137, media.add("video", data), len(data)), tmp_path / "v.part")
    ticks = count()
    seen: list[Progress] = []
    reporter = ProgressReporter("v", seen.append, clock=lambda: next(ticks) * 0.1)
    downloader(media, connections=4, reporter=reporter).run([job], video_id="v")
    done = [progress.bytes_done for progress in seen]
    assert done == sorted(done)
    assert (done[0], done[-1]) == (0, 20_000)
    assert {progress.phase for progress in seen} == {"downloading"}
    assert all(progress.bytes_total == 20_000 for progress in seen)
    assert (
        len(seen) == 8
    )  # 22 reports (start, 20 ranges, end) with 0.1 s ticks and a 0.25 s throttle


def test_a_failing_progress_callback_stops_the_download(tmp_path: Path) -> None:
    media = FakeMedia()
    data = pattern(4000)
    job = Job(media_stream(137, media.add("video", data), len(data)), tmp_path / "v.part")

    def explode(progress: Progress) -> None:
        if progress.bytes_done:
            raise ValueError("callback failed")

    reporter = ProgressReporter("v", explode, interval=0)
    with pytest.raises(ValueError, match="callback failed"):
        downloader(media, reporter=reporter).run([job], video_id="v")
    assert state_of(job)["completed"] == []


def test_a_reporter_without_a_callback_does_nothing() -> None:
    # Focused test added to close a coverage gap left by the brief's own 31 tests (see the
    # task report): a ProgressReporter built with callback=None is a valid no-op.
    reporter = ProgressReporter("v", None)
    reporter.report("downloading", 0, 100, force=True)
