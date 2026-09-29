"""Tests for download_many over a fake YouTube with several videos."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.bulk import IDS, TITLES, ManyVideos
from tests.helpers.downloads import FakeFFmpegRuns, codec_of, read_movie
from tests.helpers.files import folder_names
from utmax.adapters.ffmpeg import FFmpeg
from utmax.errors import FFmpegNotFound, InvalidOption, IpBlocked, VideoUnavailable
from utmax.models import BulkResult, DownloadResult, VideoEntry


def value(result: BulkResult[DownloadResult]) -> DownloadResult:
    assert result.value is not None
    return result.value


def test_videos_are_named_by_title_and_id(tmp_path: Path) -> None:
    folder = tmp_path / "videos"
    names = [f"{TITLES[video_id]} [{video_id}].mp4" for video_id in IDS[:2]]
    report = ManyVideos().bulk().download_many(IDS[:2], folder)
    assert [result.status for result in report] == ["ok", "ok"]
    assert [result.path for result in report] == [folder / name for name in names]
    for result in report:
        assert value(result).path == result.path
        assert value(result).embedded_subtitles == ("en",)
        tracks = read_movie(value(result).path).tracks
        assert [codec_of(track) for track in tracks] == [b"avc1", b"mp4a", b"tx3g"]
    assert folder_names(folder) == sorted(names)


def test_folder_checks_ignore_only_windows_ghost_names(tmp_path: Path) -> None:
    for name in ("RICK.M4A.140.PART.JSON.tmp", ".rick.m4a.1a2b.tmp", "rick.m4a.140.part"):
        (tmp_path / name).write_bytes(b"")
    assert folder_names(tmp_path) == [".rick.m4a.1a2b.tmp", "rick.m4a.140.part"]


def test_existing_downloads_are_skipped_without_a_request(tmp_path: Path) -> None:
    old = tmp_path / f"Old title [{IDS[0]}].mp4"
    old.write_bytes(b"old")
    youtube = ManyVideos()
    report = youtube.bulk().download_many(IDS[:2], tmp_path)
    assert [(result.status, result.path) for result in report] == [
        ("skipped", old),
        ("ok", tmp_path / f"{TITLES[IDS[1]]} [{IDS[1]}].mp4"),
    ]
    assert youtube.players == [IDS[1]]
    again = youtube.bulk().download_many(IDS[:1], tmp_path, skip_existing=False)
    assert again[0].path == tmp_path / f"{TITLES[IDS[0]]} [{IDS[0]}].mp4"
    assert old.read_bytes() == b"old"


def test_templates_number_listing_entries(tmp_path: Path) -> None:
    entries = [
        VideoEntry(video_id, TITLES[video_id], 60.0, "Rick Astley", "UC" + "x" * 22, index)
        for index, video_id in ((7, IDS[0]), (8, IDS[1]))
    ]
    report = (
        ManyVideos()
        .bulk()
        .download_many(
            entries,
            tmp_path,
            format="m4a",
            filename="{index:03d} {channel} - {title} [{video_id}].{ext}",
        )
    )
    assert [result.path.name for result in report if result.path] == [
        f"007 Rick Astley - {TITLES[IDS[0]]} [{IDS[0]}].m4a",
        f"008 Rick Astley - {TITLES[IDS[1]]} [{IDS[1]}].m4a",
    ]
    assert {(value(result).container, value(result).video_format) for result in report} == {
        ("m4a", None)
    }


def test_subtitle_languages_apply_to_every_video(tmp_path: Path) -> None:
    report = (
        ManyVideos().bulk().download_many(IDS[:2], tmp_path, subtitles=["de"], subtitle_mode="both")
    )
    for result, video_id in zip(report, IDS[:2], strict=True):
        assert value(result).embedded_subtitles == ("de-DE",)
        sidecar = tmp_path / f"{TITLES[video_id]} [{video_id}].de-DE.srt"
        assert value(result).sidecars == (sidecar,)


def test_mp3_files_are_converted_with_ffmpeg(tmp_path: Path) -> None:
    runs = FakeFFmpegRuns()
    bulk = ManyVideos().bulk(
        locate=lambda _: "ffmpeg-for-tests",
        make_ffmpeg=lambda executable: FFmpeg(executable, spawn=runs),
    )
    report = bulk.download_many(IDS[:2], tmp_path, format="mp3")
    assert [result.status for result in report] == ["ok", "ok"]
    assert all(value(result).path.read_bytes().startswith(b"ID3") for result in report)


def test_mp3_needs_ffmpeg_before_any_request(tmp_path: Path) -> None:
    def missing(_: object) -> str:
        raise FFmpegNotFound("No ffmpeg was found.")

    youtube = ManyVideos()
    with pytest.raises(FFmpegNotFound):
        youtube.bulk(locate=missing).download_many(IDS, tmp_path / "audio", format="mp3")
    assert youtube.players == []
    assert not (tmp_path / "audio").exists()


@pytest.mark.parametrize(
    "options",
    [
        {"quality": "best"},
        {"format": "mov", "quality": "max"},
        {"format": "avi"},
        {"subtitles": "en"},
        {"subtitles": [make_transcript()]},
        {"subtitle_mode": "burn"},
        {"filename": "{title}.{ext}"},
        {"filename": "{video_id}.{language_code}.{ext}"},
        {"concurrency": 0},
    ],
)
def test_bad_options_fail_before_any_request(tmp_path: Path, options: dict[str, Any]) -> None:
    youtube = ManyVideos()
    with pytest.raises(InvalidOption):
        youtube.bulk().download_many(IDS, tmp_path / "videos", **options)
    assert youtube.players == []
    assert not (tmp_path / "videos").exists()


def test_failures_are_reported_and_blocks_stop_the_run(tmp_path: Path) -> None:
    missing = ManyVideos(missing={IDS[0]}).bulk().download_many(IDS[:2], tmp_path / "a")
    assert [result.status for result in missing] == ["failed", "ok"]
    assert isinstance(missing[0].error, VideoUnavailable)
    blocked = ManyVideos(blocked={IDS[0]}).bulk()
    report = blocked.download_many(IDS, tmp_path / "b", concurrency=1)
    assert [result.status for result in report] == ["failed", "not_attempted", "not_attempted"]
    assert isinstance(report[0].error, IpBlocked)


def test_ctrl_c_stops_the_downloads(tmp_path: Path) -> None:
    def interrupt(result: BulkResult[DownloadResult]) -> None:
        raise KeyboardInterrupt

    youtube = ManyVideos()
    with pytest.raises(KeyboardInterrupt):
        youtube.bulk().download_many(IDS, tmp_path, concurrency=1, progress=interrupt)
    assert IDS[2] not in youtube.players
    assert len(list(tmp_path.glob("*.mp4"))) <= 2
