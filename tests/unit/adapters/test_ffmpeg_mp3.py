"""MP3 conversion with the real ffmpeg (``uv run pytest -m ffmpeg``)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from utmax.adapters.ffmpeg import FFmpeg, locate_ffmpeg

pytestmark = pytest.mark.ffmpeg


def test_fragmented_aac_becomes_mp3(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        if os.environ.get("UTMAX_REQUIRE_FFMPEG") == "1":
            pytest.fail("UTMAX_REQUIRE_FFMPEG=1 but ffmpeg or ffprobe is not on PATH")
        pytest.skip("ffmpeg and ffprobe are not installed")
    source = tmp_path / "song.mp3.140.part"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=2",
            "-ac",
            "2",
            "-c:a",
            "aac",
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof",
            "-frag_duration",
            "500000",
            "-f",
            "mp4",
            str(source),
        ],
        check=True,
    )
    tool = FFmpeg(locate_ffmpeg())
    tool.check_mp3()
    target = tmp_path / ".song.mp3.1a2b.tmp"
    tool.to_mp3(source, target)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,channels:format=format_name,duration",
            "-of",
            "json",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(probe.stdout)
    assert info["streams"] == [{"codec_name": "mp3", "channels": 2}]
    assert info["format"]["format_name"] == "mp3"
    assert 1.9 < float(info["format"]["duration"]) < 2.2
