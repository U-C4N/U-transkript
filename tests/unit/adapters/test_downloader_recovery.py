"""Tests for the downloader when things go wrong: resume, refresh, retries, cancel."""

from __future__ import annotations

import json
import random
import threading
from pathlib import Path
from typing import Any

import pytest

from tests.helpers.fake_media import FakeBody, FakeMedia, Fault, media_stream, pattern
from utmax.adapters.downloader import Downloader, Job, ProgressReporter
from utmax.core.downloads import PartState
from utmax.core.streams import Stream
from utmax.errors import (
    DownloadCancelled,
    DownloadIncomplete,
    IpBlocked,
    NetworkError,
    PoTokenRequired,
    StreamForbidden,
)
from utmax.models import Progress
from utmax.transport import HttpRequest

CHUNK = 1000


def downloader(media: FakeMedia, **options: Any) -> Downloader:
    options.setdefault("chunk_size", CHUNK)
    options.setdefault("sleep", lambda _: None)
    return Downloader(media.stream, **options)


def completed(job: Job) -> list[int]:
    return json.loads(job.state_path.read_text(encoding="utf-8"))["completed"]


def served(tmp_path: Path, size: int = 5000, **stream: Any) -> tuple[FakeMedia, bytes, Job]:
    """A media server with one video stream of ``size`` bytes, and a job for it."""
    media = FakeMedia()
    data = pattern(size)
    job = Job(media_stream(137, media.add("video", data), size, **stream), tmp_path / "v.part")
    return media, data, job


def save(job: Job, state: PartState) -> None:
    job.state_path.write_text(state.to_json(), encoding="utf-8")


def test_finished_ranges_are_reused_on_the_next_run(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, last_modified="7")
    job.part.write_bytes(data[:2000] + bytes(3000))
    save(job, PartState("v", 137, 5000, "7", CHUNK, frozenset({0, 1})))
    assert downloader(media).run([job], video_id="v") is True
    assert job.part.read_bytes() == data
    assert sorted(media.ranges("video")) == [
        "bytes=2000-2999",
        "bytes=3000-3999",
        "bytes=4000-4999",
    ]


@pytest.mark.parametrize(
    "saved",
    [
        PartState("v", 137, 5000, "6", CHUNK, frozenset({0, 1})).to_json(),
        PartState("v", 137, 5000, "7", 500, frozenset({0, 1})).to_json(),
        "{broken",
    ],
)
def test_resume_starts_over_when_the_saved_state_does_not_fit(tmp_path: Path, saved: str) -> None:
    media, data, job = served(tmp_path, last_modified="7")
    job.part.write_bytes(b"x" * 5000)
    job.state_path.write_text(saved, encoding="utf-8")
    assert downloader(media).run([job], video_id="v") is False
    assert job.part.read_bytes() == data
    assert len(media.ranges("video")) == 5


def test_a_part_file_of_the_wrong_size_starts_over(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, last_modified="7")
    job.part.write_bytes(data[:2000])
    save(job, PartState("v", 137, 5000, "7", CHUNK, frozenset({0, 1})))
    assert downloader(media).run([job], video_id="v") is False
    assert job.part.read_bytes() == data


def test_resume_false_ignores_the_saved_state(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, last_modified="7")
    job.part.write_bytes(data[:2000] + bytes(3000))
    save(job, PartState("v", 137, 5000, "7", CHUNK, frozenset({0, 1})))
    assert downloader(media).run([job], video_id="v", resume=False) is False
    assert len(media.ranges("video")) == 5
    assert job.part.read_bytes() == data


def test_a_403_refreshes_the_urls_once_for_every_thread(tmp_path: Path) -> None:
    """All four connections meet the stale URL's 403 before any of them refreshes, so the
    single-flight guard (not just a single-threaded coincidence) is what limits it to one."""
    media, data, job = served(tmp_path, size=8000)
    media.expired.add(job.stream.url)
    connections = 4
    barrier = threading.Barrier(connections, timeout=5)
    calls: list[int] = []

    def refresh() -> list[Stream]:
        calls.append(1)
        return [media_stream(137, job.stream.url + "?v=2", 8000)]

    def opener(request: HttpRequest) -> FakeBody:
        body = media.stream(request)
        if body.status == 403:
            barrier.wait()
        return body

    run = Downloader(
        opener, chunk_size=CHUNK, sleep=lambda _: None, connections=connections, refresh=refresh
    )
    run.run([job], video_id="v")
    assert calls == [1]
    assert job.part.read_bytes() == data


def test_forbidden_streams_give_up_after_three_refreshes(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=8000)
    media.expired.add(job.stream.url)
    calls: list[int] = []

    def refresh() -> list[Stream]:
        calls.append(1)
        url = f"{job.stream.url}?v={len(calls)}"
        media.expired.add(url)
        return [media_stream(137, url, 8000)]

    with pytest.raises(StreamForbidden, match="after 3 fresh URLs") as caught:
        downloader(media, refresh=refresh).run([job], video_id="v")
    assert caught.value.itag == 137
    assert len(calls) == 3


def test_streams_served_only_at_the_start_need_a_po_token(tmp_path: Path) -> None:
    """Without a proof-of-origin token YouTube serves only the first megabyte of some videos'
    streams and answers 403 after it (ZcDFZzsp3_Y over ANDROID and IOS, 2026-10-08)."""
    media, _, job = served(tmp_path, size=8000)
    media.start_only["video"] = 1500
    calls: list[int] = []

    def refresh() -> list[Stream]:
        calls.append(1)
        return [media_stream(137, f"{job.stream.url}?v={len(calls)}", 8000)]

    with pytest.raises(PoTokenRequired, match=r"proof-of-origin \(PO\) token") as caught:
        downloader(media, refresh=refresh, connections=1).run([job], video_id="v")
    error = caught.value
    assert "stream 137 of video v" in str(error)
    assert error.video_id == "v"
    assert "subtitles can still be fetched" in error.suggestion
    assert len(calls) == 3
    assert media.ranges("video")[-1] == "bytes=0-0"
    assert all(body.closed for body in media.bodies)


def test_a_failed_first_byte_check_keeps_the_403_error(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=8000)
    media.expired.add(job.stream.url)

    def opener(request: HttpRequest) -> FakeBody:
        if request.headers.get("Range") == "bytes=0-0":
            raise NetworkError("Could not complete GET https://media.test: connection reset")
        return media.stream(request)

    with pytest.raises(StreamForbidden, match="after 0 fresh URLs"):
        Downloader(opener, chunk_size=CHUNK, sleep=lambda _: None).run([job], video_id="v")
    assert completed(job) == []


def test_urls_about_to_expire_are_refreshed_before_use(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000, expires_at=1_000_100)
    fresh = media_stream(137, job.stream.url + "?v=2", 3000, expires_at=1_021_600)
    run = downloader(media, connections=1, refresh=lambda: [fresh], clock=lambda: 1_000_000.0)
    run.run([job], video_id="v")
    assert [request.url for request in media.requests] == [fresh.url] * 3
    assert job.part.read_bytes() == data


def test_a_refresh_that_changes_the_stream_is_reported(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.expired.add(job.stream.url)
    changed = media_stream(137, job.stream.url + "?v=2", 3000, last_modified="2")
    with pytest.raises(DownloadIncomplete, match="changed on YouTube"):
        downloader(media, refresh=lambda: [changed]).run([job], video_id="v")


def test_a_refresh_without_a_url_is_treated_as_no_match(tmp_path: Path) -> None:
    """A same-itag, same-size, same-lmt candidate with no URL (still ciphered) is not a match:
    using it would fail the next range request with a raw error instead of a utmax one."""
    media, _, job = served(tmp_path, size=3000)
    media.expired.add(job.stream.url)
    ciphered = media_stream(137, "", 3000)
    with pytest.raises(DownloadIncomplete, match="changed on YouTube"):
        downloader(media, refresh=lambda: [ciphered]).run([job], video_id="v")


def test_a_failing_refresh_propagates(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.expired.add(job.stream.url)

    def refresh() -> list[Stream]:
        raise IpBlocked("slow down", video_id="v")

    with pytest.raises(IpBlocked, match="slow down"):
        downloader(media, refresh=refresh).run([job], video_id="v")


def test_short_bodies_continue_from_the_first_missing_byte(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000)
    media.fail("video", Fault(cut_after=400))
    downloader(media, connections=1).run([job], video_id="v")
    assert media.ranges("video")[:2] == ["bytes=0-999", "bytes=400-999"]
    assert job.part.read_bytes() == data


def test_a_reset_after_progress_continues_at_once(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000)
    media.fail("video", Fault(reset_after=300))
    delays: list[float] = []
    downloader(media, connections=1, sleep=delays.append).run([job], video_id="v")
    assert media.ranges("video")[:2] == ["bytes=0-999", "bytes=300-999"]
    assert delays == []
    assert job.part.read_bytes() == data


def test_failures_without_progress_back_off(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000)
    media.fail("video", Fault(error=NetworkError("refused")), Fault(status=503), Fault(status=429))
    delays: list[float] = []
    run = downloader(media, connections=1, sleep=delays.append, rng=random.Random(1))
    run.run([job], video_id="v")
    assert len(delays) == 3
    assert delays == sorted(delays)
    assert 0.5 <= delays[0] <= 0.75
    assert 2.0 <= delays[2] <= 2.25
    assert job.part.read_bytes() == data


def test_network_failures_give_up_after_the_last_attempt(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", *[Fault(error=NetworkError("refused"))] * 5)
    with pytest.raises(NetworkError, match="refused"):
        downloader(media, connections=1).run([job], video_id="v")
    assert len(media.requests) == 5


def test_statuses_that_stay_bad_become_download_incomplete(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", *[Fault(status=503)] * 5)
    with pytest.raises(DownloadIncomplete, match="kept failing"):
        downloader(media, connections=1).run([job], video_id="v")


def test_a_416_refreshes_once_then_gives_up(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", Fault(status=416), Fault(status=416))
    calls: list[int] = []

    def refresh() -> list[Stream]:
        calls.append(1)
        return [job.stream]

    with pytest.raises(DownloadIncomplete, match="HTTP 416"):
        downloader(media, connections=1, refresh=refresh).run([job], video_id="v")
    assert calls == [1]


def test_a_single_416_recovers(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000)
    media.fail("video", Fault(status=416))
    downloader(media, connections=1).run([job], video_id="v")
    assert job.part.read_bytes() == data


def test_servers_that_ignore_ranges_are_rejected(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", Fault(ignore_range=True))
    with pytest.raises(DownloadIncomplete, match="ignored the byte range"):
        downloader(media, connections=1).run([job], video_id="v")


def test_whole_stream_requests_accept_a_plain_200(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=1500)
    media.fail("video", Fault(ignore_range=True))
    downloader(media).run([job], video_id="v")
    assert job.part.read_bytes() == data


def test_other_statuses_end_the_download(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=3000)
    media.fail("video", Fault(status=404))
    with pytest.raises(DownloadIncomplete, match="answered HTTP 404"):
        downloader(media, connections=1).run([job], video_id="v")


def test_cancel_keeps_the_finished_ranges_for_a_resume(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=6000)
    cancel = threading.Event()

    def watch(progress: Progress) -> None:
        if progress.bytes_done >= 2000:
            cancel.set()

    reporter = ProgressReporter("v", watch, interval=0)
    with pytest.raises(DownloadCancelled, match="cancelled"):
        downloader(media, connections=1, cancel=cancel, reporter=reporter).run([job], video_id="v")
    assert completed(job) == [0, 1]
    assert downloader(media, connections=1).run([job], video_id="v") is True
    assert job.part.read_bytes() == data


def test_ctrl_c_saves_the_state_and_propagates(tmp_path: Path) -> None:
    media, _, job = served(tmp_path, size=6000)

    def interrupt(progress: Progress) -> None:
        if progress.bytes_done >= 2000:
            raise KeyboardInterrupt

    reporter = ProgressReporter("v", interrupt, interval=0)
    with pytest.raises(KeyboardInterrupt):
        downloader(media, connections=1, reporter=reporter).run([job], video_id="v")
    assert completed(job) == [0]


# The tests below were added to close coverage gaps left by the brief's own 31 tests (see the
# task report): they are focused, deterministic and do not touch the verbatim tests above.


def test_a_stream_whose_size_cannot_be_probed_fails(tmp_path: Path) -> None:
    media = FakeMedia()
    job = Job(media_stream(137, media.add("video", pattern(2500)), None), tmp_path / "v.part")
    media.fail("video", Fault(status=404))
    with pytest.raises(DownloadIncomplete, match="Could not learn the size"):
        downloader(media).run([job], video_id="v")


def test_an_empty_response_is_retried(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, size=3000)
    media.fail("video", Fault(cut_after=0))
    downloader(media, connections=1).run([job], video_id="v")
    assert media.ranges("video")[:2] == ["bytes=0-999", "bytes=0-999"]
    assert job.part.read_bytes() == data


def test_a_missing_part_file_starts_over(tmp_path: Path) -> None:
    media, data, job = served(tmp_path, last_modified="7")
    save(job, PartState("v", 137, 5000, "7", CHUNK, frozenset({0, 1})))
    assert downloader(media).run([job], video_id="v") is False
    assert job.part.read_bytes() == data
