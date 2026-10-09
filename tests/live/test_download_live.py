"""Live download checks against YouTube (``uv run pytest -m live``); files go to tmp_path.

Most use "Me at the zoo" (jNQXAC9IVRw): 19 seconds, 240p, manual English subtitles. Without a
visitorData, VISIONOS and ANDROID_VR asked for a bot check on it (2026-10-09). The dubbed-audio
checks use ZcDFZzsp3_Y, an English video with about twenty automatically dubbed audio tracks.
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
DUBBED = "ZcDFZzsp3_Y"


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
    assert result.video_format.codec in ("h264", "av1")
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
        assert codecs == [result.video_format.codec, "aac", "mov_text"]


@pytest.mark.parametrize("video", [ZOO, "9bZkp7q19f0", DUBBED])
def test_videos_play_through_visionos(video: str) -> None:
    formats = utmax.list_formats(video)
    assert {fmt.kind for fmt in formats} == {"video", "audio"}


def test_resolution_caps_a_download_and_dubbed_videos_keep_their_original_audio(
    tmp_path: Path,
) -> None:
    result = utmax.download(DUBBED, tmp_path / "small.mp4", resolution=144, subtitles=[])
    assert result.video_format is not None
    assert min(n for n in (result.video_format.width, result.video_format.height) if n) <= 144
    assert (result.audio_format.language, result.audio_format.is_original) == ("en-US", True)
    assert utmax.fetch(DUBBED).language_code == "en"


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
