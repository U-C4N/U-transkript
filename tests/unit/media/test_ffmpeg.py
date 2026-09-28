"""End-to-end checks with the real ffmpeg: fragments made by ffmpeg, muxed by utmax, read by ffprobe.

Run with ``uv run pytest -m ffmpeg``. Without ffmpeg and ffprobe on PATH these tests are skipped,
unless ``UTMAX_REQUIRE_FFMPEG=1`` (set in CI) turns the skip into a failure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn

import pytest

from tests.helpers.builders import make_transcript
from utmax.adapters.files import FileByteSource, write_mux_plan
from utmax.core.formats import to_srt
from utmax.core.media.moov import Flavor
from utmax.core.media.mux import plan_mux
from utmax.core.media.progressive import parse_progressive
from utmax.models import Segment, Transcript

pytestmark = pytest.mark.ffmpeg

FRAGMENTED = ["-movflags", "frag_keyframe+empty_moov+default_base_moof"]
ENGLISH = make_transcript(
    Segment(0.5, 1.0, "Hello"), Segment(2.0, 1.2, "World\nsecond line"), Segment(3.3, 0.5, "End")
)
TURKISH = replace(
    make_transcript(
        Segment(0.5, 1.0, "Merhaba"),
        Segment(2.0, 1.2, "D\xfcnya \U0000011f\U0000015f\U00000131"),
        language_code="tr",
        language="Turkish",
        is_generated=True,
    ),
    translated_from="en",
    translator="claude=claude-opus-5",
)


@dataclass(frozen=True)
class Tools:
    ffmpeg: str
    ffprobe: str
    encoders: str


@pytest.fixture(scope="module")
def tools() -> Tools:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        _unavailable("ffmpeg and ffprobe are not installed")
    encoders = run([ffmpeg, "-hide_banner", "-encoders"]).stdout
    if "libx264" not in encoders:
        _unavailable("this ffmpeg build has no libx264 encoder")
    return Tools(ffmpeg, ffprobe, encoders)


def _unavailable(reason: str) -> NoReturn:
    if os.environ.get("UTMAX_REQUIRE_FFMPEG") == "1":
        pytest.fail(f"UTMAX_REQUIRE_FFMPEG=1 but {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="module")
def streams(tools: Tools, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("fragments")
    video = ["-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=4", "-pix_fmt", "yuv420p"]
    x264 = ["-c:v", "libx264", "-preset", "ultrafast", "-g", "25", "-bf", "2"]
    audio = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=4", "-ac", "2"]
    made = {
        "h264": [*video, *x264, *FRAGMENTED],
        "h264-negative-cts": [
            *video,
            *x264,
            "-movflags",
            "frag_keyframe+empty_moov+default_base_moof+negative_cts_offsets",
        ],
        "aac": [*audio, "-c:a", "aac", "-b:a", "64k", *FRAGMENTED, "-frag_duration", "1000000"],
    }
    if "libaom-av1" in tools.encoders:
        made["av1"] = [*video, "-c:v", "libaom-av1", "-cpu-used", "8", "-g", "25", *FRAGMENTED]
    paths: dict[str, Path] = {}
    for name, arguments in made.items():
        paths[name] = folder / f"{name}.mp4"
        run(
            [tools.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *arguments, str(paths[name])]
        )
    return paths


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    return result


def mux(
    inputs: list[Path],
    target: Path,
    flavor: Flavor,
    subtitles: list[Transcript],
    default: str | None = None,
) -> Path:
    sources = [FileByteSource(path) for path in inputs]
    try:
        plan = plan_mux(sources, flavor=flavor, subtitles=subtitles, default_subtitle=default)
        return write_mux_plan(plan, sources, target)
    finally:
        for source in sources:
            source.close()


def probe(tools: Tools, path: Path) -> list[dict[str, Any]]:
    output = run(
        [tools.ffprobe, "-v", "error", "-count_packets", "-show_streams", "-of", "json", str(path)]
    )
    streams: list[dict[str, Any]] = json.loads(output.stdout)["streams"]
    return streams


def packet_times(tools: Tools, path: Path, stream: str) -> list[tuple[int, int]]:
    output = run(
        [
            tools.ffprobe,
            "-v",
            "error",
            "-select_streams",
            stream,
            "-show_entries",
            "packet=pts,dts",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    return [
        (int(pts), int(dts)) for pts, dts, *_ in (line.split(",") for line in output.stdout.split())
    ]


def decodes_cleanly(tools: Tools, path: Path) -> None:
    result = run(
        [
            tools.ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-f",
            "null",
            "-",
        ]
    )
    assert result.stderr == ""


def extracted_srt(tools: Tools, path: Path, index: int) -> str:
    output = run(
        [tools.ffmpeg, "-v", "error", "-i", str(path), "-map", f"0:s:{index}", "-f", "srt", "-"]
    )
    return re.sub(r"</?font[^>]*>", "", output.stdout).strip()


def test_mp4_with_two_subtitle_tracks(
    tools: Tools, streams: dict[str, Path], tmp_path: Path
) -> None:
    out = mux(
        [streams["h264"], streams["aac"]], tmp_path / "out.mp4", "mp4", [ENGLISH, TURKISH], "tr"
    )
    info = probe(tools, out)
    assert [s["codec_name"] for s in info] == ["h264", "aac", "mov_text", "mov_text"]
    with FileByteSource(out) as output:
        parsed = parse_progressive(output)
    assert [int(s["nb_read_packets"]) for s in info] == [len(t.samples) for t in parsed.tracks]
    sources = probe(tools, streams["h264"]) + probe(tools, streams["aac"])
    assert [s["nb_read_packets"] for s in info[:2]] == [s["nb_read_packets"] for s in sources]
    assert [s["disposition"]["default"] for s in info[2:]] == [0, 1]
    assert [s["tags"]["language"] for s in info[2:]] == ["eng", "tur"]
    assert info[3]["tags"]["handler_name"] == "Turkish (AI: claude=claude-opus-5)"
    assert packet_times(tools, out, "v:0") == packet_times(tools, streams["h264"], "v:0")
    decodes_cleanly(tools, out)
    assert extracted_srt(tools, out, 0) == to_srt(ENGLISH.segments).strip()
    assert extracted_srt(tools, out, 1) == to_srt(TURKISH.segments).strip()


def test_mov_with_a_subtitle_track(tools: Tools, streams: dict[str, Path], tmp_path: Path) -> None:
    out = mux([streams["h264"], streams["aac"]], tmp_path / "out.mov", "mov", [TURKISH])
    info = probe(tools, out)
    assert [s["codec_name"] for s in info] == ["h264", "aac", "mov_text"]
    assert info[2]["tags"]["language"] == "tur"
    assert info[2]["tags"]["handler_name"] == "Turkish (AI: claude=claude-opus-5)"
    assert packet_times(tools, out, "a:0") == packet_times(tools, streams["aac"], "a:0")
    decodes_cleanly(tools, out)
    assert extracted_srt(tools, out, 0) == to_srt(TURKISH.segments).strip()


def test_m4a(tools: Tools, streams: dict[str, Path], tmp_path: Path) -> None:
    out = mux([streams["aac"]], tmp_path / "out.m4a", "m4a", [])
    (audio,) = probe(tools, out)
    assert audio["codec_name"] == "aac"
    assert audio["nb_read_packets"] == probe(tools, streams["aac"])[0]["nb_read_packets"]
    decodes_cleanly(tools, out)


def test_negative_composition_offsets(
    tools: Tools, streams: dict[str, Path], tmp_path: Path
) -> None:
    source = streams["h264-negative-cts"]
    out = mux([source, streams["aac"]], tmp_path / "negative.mp4", "mp4", [])
    with FileByteSource(out) as output:
        assert parse_progressive(output).tracks[0].ctts_version == 1
    decodes_cleanly(tools, out)
    before, after = packet_times(tools, source, "v:0"), packet_times(tools, out, "v:0")
    assert [pts - before[0][0] for pts, _ in before] == [pts - after[0][0] for pts, _ in after]


def test_av1(tools: Tools, streams: dict[str, Path], tmp_path: Path) -> None:
    if "av1" not in streams:
        pytest.skip("this ffmpeg build has no libaom-av1 encoder")
    out = mux([streams["av1"], streams["aac"]], tmp_path / "av1.mp4", "mp4", [ENGLISH])
    assert [s["codec_name"] for s in probe(tools, out)] == ["av1", "aac", "mov_text"]
    with FileByteSource(out) as output:
        brands = parse_progressive(output).compatible_brands
    assert brands == ("isom", "iso2", "av01", "mp41")
    decodes_cleanly(tools, out)
