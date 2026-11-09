"""What makes a download start sooner: streams reused for a while, subtitles fetched together."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.bulk import IDS, ManyVideos
from utmax import Client
from utmax.errors import UTMaxError
from utmax.models import Segment, Track, Transcript, VideoInfo
from utmax.services import download as download_service
from utmax.services.download import _fetch_all

VIDEO = IDS[0]


def test_list_formats_then_download_asks_youtube_for_the_streams_once(tmp_path: Path) -> None:
    youtube = ManyVideos()
    client = Client(transport=youtube)
    client.list_formats(VIDEO)
    client.download(VIDEO, tmp_path / "a.m4a")
    assert youtube.players == [VIDEO]


def test_the_streams_are_asked_for_again_once_they_are_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download_service, "PLAYER_TTL", 0.0)
    youtube = ManyVideos()
    client = Client(transport=youtube)
    client.list_formats(VIDEO)
    client.download(VIDEO, tmp_path / "a.m4a")
    assert youtube.players == [VIDEO, VIDEO]


def test_a_failed_download_starts_the_next_one_from_fresh_streams(tmp_path: Path) -> None:
    youtube = ManyVideos()
    client = Client(transport=youtube)
    with pytest.raises(UTMaxError):
        client.download(VIDEO, tmp_path / "v.mp4", subtitles=["xx"])  # no such subtitles
    client.download(VIDEO, tmp_path / "a.m4a")
    assert youtube.players == [VIDEO, VIDEO]


class Barrier:
    """A track fetcher that answers only once ``parties`` fetches are running together."""

    def __init__(self, parties: int) -> None:
        self.barrier = threading.Barrier(parties, timeout=5)
        self.threads: set[str] = set()

    def fetch_track(self, track: Track, *, preserve_formatting: bool) -> Transcript:
        self.threads.add(threading.current_thread().name)
        self.barrier.wait()
        return make_transcript(Segment(0.0, 1.0, track.language), language_code=track.language_code)


def track(code: str, fetcher: Barrier) -> Track:
    info = VideoInfo(VIDEO, "title", "channel", "UC" + "x" * 22, 1.0, is_live_content=False)
    return Track(info, code, code, is_generated=False, is_translatable=False, _fetcher=fetcher)


def test_subtitles_are_fetched_together_and_kept_in_order() -> None:
    fetcher = Barrier(3)
    given = make_transcript(Segment(0.0, 1.0, "mine"), language_code="tr")
    chosen = [track("de", fetcher), given, track("en", fetcher), track("fr", fetcher)]
    fetched = _fetch_all(chosen)
    assert [transcript.language_code for transcript in fetched] == ["de", "tr", "en", "fr"]
    assert fetched[1] is given
    assert len(fetcher.threads) == 3  # all three waited for each other, so they ran together


def test_one_subtitle_is_fetched_without_threads() -> None:
    fetcher = Barrier(1)
    (fetched,) = _fetch_all([track("de", fetcher)])
    assert fetched.language_code == "de"
    assert fetcher.threads == {threading.current_thread().name}


def test_only_the_latest_videos_streams_are_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(download_service, "_MAX_PLAYERS", 1)
    youtube = ManyVideos()
    client = Client(transport=youtube)
    client.list_formats(IDS[0])
    client.list_formats(IDS[1])  # pushes the first video out
    client.list_formats(IDS[1])
    client.list_formats(IDS[0])
    assert youtube.players == [IDS[0], IDS[1], IDS[0]]
