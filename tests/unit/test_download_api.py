"""Tests for utmax.download and Client.download."""

from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import utmax
from tests.helpers.downloads import FakeYouTube
from tests.helpers.youtube import VIDEO_ID
from utmax import Client
from utmax.transport import HttpRequest, HttpResponse

PARAMETERS = [
    "video",
    "path",
    "format",
    "quality",
    "subtitles",
    "subtitle_mode",
    "default_subtitle",
    "connections",
    "chunk_size",
    "resume",
    "overwrite",
    "ffmpeg",
    "progress",
    "cancel",
]


class SendOnly:
    """A custom transport without ``stream()``: downloads fall back to buffered ranges."""

    def __init__(self, youtube: FakeYouTube) -> None:
        self._youtube = youtube

    def send(self, request: HttpRequest) -> HttpResponse:
        if request.url.startswith("https://media.test/"):
            return self._youtube.media.send(request)
        return self._youtube.api.send(request)


def test_client_downloads_through_its_transport(tmp_path: Path) -> None:
    with Client(transport=FakeYouTube()) as client:
        result = client.download(VIDEO_ID, tmp_path / "rick.mp4")
    assert result.embedded_subtitles == ("en",)
    assert result.path.exists()


def test_the_facade_uses_the_default_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(utmax, "_default_client", Client(transport=FakeYouTube()))
    result = utmax.download(f"https://youtu.be/{VIDEO_ID}", tmp_path / "rick.m4a")
    assert result.audio_format.itag == 140


def test_download_signature_matches_the_spec() -> None:
    parameters = inspect.signature(utmax.download).parameters
    assert list(parameters) == PARAMETERS
    assert parameters["chunk_size"].default == 2 * 2**20
    assert (parameters["quality"].default, parameters["subtitle_mode"].default) == (
        "compat",
        "embed",
    )
    assert list(inspect.signature(Client.download).parameters)[1:] == PARAMETERS


def test_download_is_exported() -> None:
    assert "download" in utmax.__all__
    assert callable(utmax.download)


def test_one_client_downloads_in_parallel_threads(tmp_path: Path) -> None:
    client = Client(transport=FakeYouTube())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda n: client.download(VIDEO_ID, tmp_path / f"rick{n}.m4a"), range(4))
        )
    assert [result.path.name for result in results] == [f"rick{n}.m4a" for n in range(4)]
    assert len({result.size_bytes for result in results}) == 1


def test_custom_transports_without_streaming_still_download(tmp_path: Path) -> None:
    result = Client(transport=SendOnly(FakeYouTube())).download(VIDEO_ID, tmp_path / "rick.m4a")
    assert result.size_bytes > 0


def test_downloads_print_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    Client(transport=FakeYouTube()).download(VIDEO_ID, tmp_path / "rick.mp4")
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
