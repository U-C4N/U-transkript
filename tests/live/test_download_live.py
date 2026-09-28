"""Live download checks against YouTube (``uv run pytest -m live``); files go to tmp_path.

They use "Me at the zoo" (jNQXAC9IVRw): 19 seconds, 240p H.264, manual English subtitles, and
ANDROID_VR asks for a bot check on it, so the stream-client fallback is exercised too.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

import utmax
from utmax.adapters.files import FileByteSource
from utmax.core.downloads import MIN_CHUNK_SIZE
from utmax.core.media.progressive import parse_progressive
from utmax.errors import DownloadCancelled

pytestmark = pytest.mark.live

ZOO = "jNQXAC9IVRw"


def handlers(path: Path) -> list[str]:
    with FileByteSource(path) as source:
        return [track.handler for track in parse_progressive(source).tracks]


def test_m4a_download(tmp_path: Path) -> None:
    result = utmax.download(ZOO, tmp_path / "zoo.m4a")
    assert result.audio_format.codec == "aac"
    assert result.size_bytes > 100_000
    assert handlers(result.path) == ["soun"]


def test_mp4_download_with_embedded_english(tmp_path: Path) -> None:
    result = utmax.download(ZOO, tmp_path)
    assert result.path.name == "Me at the zoo [jNQXAC9IVRw].mp4"
    assert result.video_format is not None
    assert result.video_format.codec == "h264"
    assert result.embedded_subtitles == ("en",)
    assert handlers(result.path) == ["vide", "soun", "sbtl"]
    if shutil.which("ffprobe"):
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "json",
                str(result.path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        codecs = [stream["codec_name"] for stream in json.loads(probe.stdout)["streams"]]
        assert codecs == ["h264", "aac", "mov_text"]


def test_a_download_cancelled_while_muxing_resumes_without_downloading_again(
    tmp_path: Path,
) -> None:
    cancel = threading.Event()

    def stop_while_muxing(progress: utmax.Progress) -> None:
        if progress.phase == "muxing":
            cancel.set()

    with pytest.raises(DownloadCancelled):
        utmax.download(
            ZOO,
            tmp_path / "zoo.mp4",
            chunk_size=MIN_CHUNK_SIZE,
            progress=stop_while_muxing,
            cancel=cancel,
        )
    assert list(tmp_path.glob("zoo.mp4.*.part"))
    result = utmax.download(ZOO, tmp_path / "zoo.mp4", chunk_size=MIN_CHUNK_SIZE)
    assert result.resumed
    assert not list(tmp_path.glob("*.part*"))


def test_mp3_download(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is not installed")
    result = utmax.download(ZOO, tmp_path / "zoo.mp3")
    assert result.container == "mp3"
    assert result.size_bytes > 50_000
