"""Live listing and bulk checks against YouTube (``uv run pytest -m live``).

They use Rick Astley's channel (hundreds of uploads, Shorts and live streams) and jawed's
channel, which holds a single video ("Me at the zoo") and no Shorts or live streams.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import utmax
from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.adapters.innertube import InnerTubeClient
from utmax.core.browse import parse_browse_page
from utmax.core.clients import WEB
from utmax.errors import CollectionNotFound, CollectionUnavailable

pytestmark = pytest.mark.live

RICK = "UCuAXFkgsw1L7xaCfnd5JJOw"
ZOO = "jNQXAC9IVRw"


def test_a_handle_resolves_to_its_channel() -> None:
    videos = utmax.list_videos("@RickAstleyYT", kind="videos", limit=5)
    assert videos.source_id == f"UULF{RICK[2:]}"
    assert len(videos) == 5
    assert {entry.channel_id for entry in videos} == {RICK}
    assert all(entry.duration for entry in videos)


def test_listings_cross_pages_without_repeats() -> None:
    videos = utmax.list_videos(f"https://www.youtube.com/channel/{RICK}", limit=45)
    video_ids = [entry.video_id for entry in videos]
    assert len(video_ids) == len(set(video_ids)) == 45
    assert [entry.index for entry in videos] == list(range(1, 46))


def test_a_whole_listing_matches_the_count_youtube_shows() -> None:
    videos = utmax.list_videos("https://www.youtube.com/@jawed")
    assert videos.video_count == 1
    assert [entry.video_id for entry in videos] == [ZOO]


def test_kinds_a_channel_lacks_are_empty() -> None:
    shorts = utmax.list_videos("@jawed", kind="shorts")
    assert (len(shorts), shorts.video_count, shorts.kind) == (0, 0, "shorts")


def test_shorts_and_live_streams_have_their_own_lists() -> None:
    shorts = utmax.list_videos("@RickAstleyYT", kind="shorts", limit=3)
    live = utmax.list_videos("@RickAstleyYT", kind="live", limit=3)
    assert (len(shorts), shorts.source_id) == (3, f"UUSH{RICK[2:]}")
    assert live.source_id == f"UULV{RICK[2:]}"
    assert len(live) >= 1


def test_the_web_client_still_reads_upload_lists() -> None:
    innertube = InnerTubeClient(RetryingTransport(UrllibTransport()))
    page = parse_browse_page(innertube.browse(WEB, browse_id=f"VLUULF{RICK[2:]}"))
    assert page.items >= 50
    assert page.continuation is not None
    assert all(video.duration for video in page.videos[:10])
    assert page.video_count is not None


def test_missing_playlists_and_mixes_are_reported() -> None:
    with pytest.raises(CollectionNotFound):
        utmax.list_videos("PLnotaplaylist000000000000000000")
    with pytest.raises(CollectionUnavailable):
        utmax.list_videos("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ")


def test_fetch_many_saves_one_file_per_video_and_skips_them_next_time(tmp_path: Path) -> None:
    report = utmax.fetch_many([ZOO, "dQw4w9WgXcQ"], out_dir=tmp_path)
    # A block is reported per video, not raised; raising it lets conftest.py skip the test.
    report.raise_for_errors()
    assert [result.status for result in report] == ["ok", "ok"]
    assert sorted(path.name for path in tmp_path.glob("*.srt")) == [
        "dQw4w9WgXcQ.en.srt",
        f"{ZOO}.en.srt",
    ]
    assert utmax.fetch_many([ZOO], out_dir=tmp_path)[0].status == "skipped"
