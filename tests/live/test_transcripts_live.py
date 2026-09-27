"""Live acceptance checks (spec §8.10) on dQw4w9WgXcQ."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

import utmax
from utmax.adapters.http import RetryingTransport, UrllibTransport
from utmax.transport import HttpRequest, HttpResponse

pytestmark = pytest.mark.live

VIDEO = "dQw4w9WgXcQ"


class RecordingTransport:
    def __init__(self) -> None:
        self.inner = RetryingTransport(UrllibTransport())
        self.urls: list[str] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.urls.append(request.url)
        return self.inner.send(request)


def test_default_fetch_returns_the_manual_english_track() -> None:
    transcript = utmax.fetch(f"https://youtu.be/{VIDEO}")
    assert (transcript.language_code, transcript.is_generated) == ("en", False)
    assert transcript.segments[1].text == "♪ We're no strangers to love ♪"


def test_language_order_never_uses_youtube_translation() -> None:
    transport = RecordingTransport()
    transcript = utmax.Client(transport=transport).fetch(VIDEO, languages=["tr", "en"])
    assert (transcript.language_code, transcript.is_generated) == ("en", False)
    assert not any("tlang=" in url for url in transport.urls)


def test_base_language_match() -> None:
    assert utmax.fetch(VIDEO, languages=["de"]).language_code == "de-DE"


def test_list_tracks() -> None:
    tracks = utmax.list_tracks(VIDEO)
    assert len(tracks) == 6
    english = [track for track in tracks if track.language_code == "en"]
    assert sorted(track.is_generated for track in english) == [False, True]
    assert tracks.video.title


def test_auto_track_merges_into_ordered_cues() -> None:
    auto = utmax.fetch(VIDEO, include_manual=False)
    merged = auto.merge_sentences()
    assert merged
    assert auto.is_generated
    for current, following in pairwise(merged):
        assert current.end <= following.start + 1e-9


def test_every_format_saves_as_utf8(tmp_path: Path) -> None:
    transcript = utmax.fetch(VIDEO)
    for name in ("r.srt", "r.vtt", "r.json", "r.txt"):
        data = transcript.save(tmp_path / name).read_bytes()
        assert "♪".encode() in data
        assert b"\r\n" not in data
