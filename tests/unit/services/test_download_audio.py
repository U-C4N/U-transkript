"""Tests for audio downloads, targets and early checks (fake YouTube, real files and muxer)."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.downloads import FakeFFmpegRuns, FakeYouTube, read_movie
from tests.helpers.youtube import VIDEO_ID
from utmax.adapters import ffmpeg as ffmpeg_module
from utmax.errors import (
    DownloadCancelled,
    FFmpegNotFound,
    InvalidOption,
    InvalidVideoId,
    OutputExists,
    StreamForbidden,
    UnsupportedFormat,
)
from utmax.models import Progress
from utmax.services.download import DownloadOptions

TITLE_FILE = "Rick Astley - Never Gonna Give You Up (Official Video) [dQw4w9WgXcQ]"


@pytest.fixture(autouse=True)
def fresh_probe_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_module, "_mp3_support", {})


def test_m4a_downloads_remux_the_aac_stream(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert result.path == tmp_path / "rick.m4a"
    assert (result.container, result.video_format, result.audio_format.itag) == ("m4a", None, 140)
    assert (result.embedded_subtitles, result.sidecars, result.resumed) == ((), (), False)
    assert result.size_bytes == result.path.stat().st_size
    movie = read_movie(result.path)
    assert movie.major_brand == "M4A "
    assert [track.handler for track in movie.tracks] == ["soun"]
    assert len(movie.tracks[0].samples) == 172
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rick.m4a"]
    assert youtube.api.urls("GET") == []


def test_missing_parent_folders_are_created(tmp_path: Path) -> None:
    target = tmp_path / "new" / "folder" / "rick.m4a"
    result = FakeYouTube().service().download(VIDEO_ID, target, DownloadOptions())
    assert result.path == target
    assert target.exists()


def test_folders_get_files_named_after_the_title(tmp_path: Path) -> None:
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path, DownloadOptions(format="m4a"))
    assert result.path == tmp_path / f"{TITLE_FILE}.m4a"


def test_existing_files_are_refused_before_any_request(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    (tmp_path / "rick.m4a").write_bytes(b"old")
    with pytest.raises(OutputExists, match="already exists"):
        youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert (youtube.api.requests, youtube.media.requests) == ([], [])


def test_overwrite_replaces_the_file(tmp_path: Path) -> None:
    (tmp_path / "rick.m4a").write_bytes(b"old")
    options = DownloadOptions(overwrite=True)
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.m4a", options)
    assert result.path.read_bytes()[4:8] == b"ftyp"


def test_folder_targets_are_checked_once_the_title_is_known(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    (tmp_path / f"{TITLE_FILE}.m4a").write_bytes(b"old")
    with pytest.raises(OutputExists):
        youtube.service().download(VIDEO_ID, tmp_path, DownloadOptions(format="m4a"))
    assert youtube.media.requests == []


@pytest.mark.parametrize(
    ("name", "options", "error", "match"),
    [
        ("rick.mp4", DownloadOptions(quality="best"), InvalidOption, "quality="),
        ("rick.mp4", DownloadOptions(subtitle_mode="burn"), InvalidOption, "subtitle_mode="),
        ("rick.mp4", DownloadOptions(connections=0), InvalidOption, "connections must be"),
        ("rick.mp4", DownloadOptions(connections=17), InvalidOption, "connections must be"),
        ("rick.mp4", DownloadOptions(chunk_size=1000), InvalidOption, "chunk_size must be"),
        ("rick.mp4", DownloadOptions(subtitles="en"), InvalidOption, "subtitles must be a list"),
        (
            "rick.mp4",
            DownloadOptions(subtitles=make_transcript()),
            InvalidOption,
            "subtitles must be a list",
        ),
        (
            "rick.mp4",
            DownloadOptions(subtitles=[123]),
            InvalidOption,
            "Each subtitle must be",
        ),
        ("rick.mov", DownloadOptions(quality="max"), InvalidOption, r"needs \.mp4"),
        ("rick.m4a", DownloadOptions(default_subtitle="en"), InvalidOption, "cannot embed"),
        ("rick.avi", DownloadOptions(), UnsupportedFormat, "Cannot tell the file type"),
        ("rick.mp4", DownloadOptions(format="mp3"), InvalidOption, "does not match"),
    ],
)
def test_bad_options_fail_before_any_request(
    tmp_path: Path,
    name: str,
    options: DownloadOptions,
    error: type[Exception],
    match: str,
) -> None:
    youtube = FakeYouTube()
    with pytest.raises(error, match=match):
        youtube.service().download(VIDEO_ID, tmp_path / name, options)
    assert (youtube.api.requests, youtube.media.requests) == ([], [])


def test_invalid_video_ids_fail_first(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    with pytest.raises(InvalidVideoId):
        youtube.service().download("not a video", tmp_path / "x.mp4", DownloadOptions())
    assert youtube.api.requests == []


def test_mp3_needs_ffmpeg_before_any_request(tmp_path: Path) -> None:
    youtube = FakeYouTube()

    def missing(_: object) -> str:
        raise FFmpegNotFound("no ffmpeg here")

    with pytest.raises(FFmpegNotFound):
        youtube.service(locate=missing).download(VIDEO_ID, tmp_path / "song.mp3", DownloadOptions())
    assert youtube.api.requests == []


def test_mp3_downloads_convert_the_audio_with_ffmpeg(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    runs = FakeFFmpegRuns()
    seen: list[Progress] = []
    options = DownloadOptions(progress=seen.append)
    result = runs.service(youtube).download(VIDEO_ID, tmp_path / "song.mp3", options)
    assert (result.container, result.video_format) == ("mp3", None)
    assert result.path.read_bytes().startswith(b"ID3")
    conversion = next(call for call in runs.calls if "-i" in call)
    assert conversion[conversion.index("-i") + 1] == str(tmp_path / "song.mp3.140.part")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["song.mp3"]
    phases = [progress.phase for progress in seen]
    assert "converting" in phases
    assert phases == sorted(phases, key=["downloading", "converting", "finished"].index)


def missing_ffmpeg(_: object) -> str:
    raise FFmpegNotFound("no ffmpeg here")


@pytest.mark.parametrize(
    ("name", "options", "service_options", "error"),
    [
        ("rick.mp4", DownloadOptions(connections=0), {}, InvalidOption),
        ("rick.avi", DownloadOptions(), {}, UnsupportedFormat),
        ("song.mp3", DownloadOptions(), {"locate": missing_ffmpeg}, FFmpegNotFound),
        ("rick.mp4", DownloadOptions(subtitles=["en"], default_subtitle="de"), {}, InvalidOption),
    ],
)
def test_errors_name_the_video(
    tmp_path: Path,
    name: str,
    options: DownloadOptions,
    service_options: dict[str, object],
    error: type[Exception],
) -> None:
    with pytest.raises(error) as caught:
        FakeYouTube().service(**service_options).download(VIDEO_ID, tmp_path / name, options)
    assert getattr(caught.value, "video_id", None) == VIDEO_ID


def test_parts_that_cannot_be_deleted_do_not_fail_a_finished_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    unlink = Path.unlink

    def locked(self: Path, missing_ok: bool = False) -> None:
        if self.name.endswith(".part"):
            raise PermissionError(13, "The file is being used by another process", str(self))
        unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    options = DownloadOptions(subtitles=["en"])
    with caplog.at_level(logging.WARNING, logger="utmax.download"):
        result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.m4a", options)
    assert result.path.exists()
    assert result.sidecars == (tmp_path / "rick.en.srt",)
    assert "could not delete rick.m4a.140.part" in caplog.text


def test_audio_files_write_requested_subtitles_next_to_them(tmp_path: Path) -> None:
    options = DownloadOptions(subtitles=["en"])
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.m4a", options)
    assert result.sidecars == (tmp_path / "rick.en.srt",)
    assert result.embedded_subtitles == ()
    assert "We're no strangers to love" in result.sidecars[0].read_text(encoding="utf-8")


def test_progress_goes_through_download_mux_and_finish(tmp_path: Path) -> None:
    seen: list[Progress] = []
    options = DownloadOptions(progress=seen.append)
    result = FakeYouTube().service().download(VIDEO_ID, tmp_path / "rick.m4a", options)
    phases = [progress.phase for progress in seen]
    assert (phases[0], phases[-1]) == ("downloading", "finished")
    assert "muxing" in phases
    order = ["downloading", "muxing", "finished"]
    assert phases == sorted(phases, key=order.index)
    assert seen[-1].bytes_done == result.size_bytes


def test_cancel_during_mux_keeps_the_parts_for_a_resume(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    cancel = threading.Event()

    def watch(progress: Progress) -> None:
        if progress.phase == "muxing":
            cancel.set()

    options = DownloadOptions(progress=watch, cancel=cancel)
    with pytest.raises(DownloadCancelled):
        youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", options)
    assert (tmp_path / "rick.m4a.140.part").exists()
    assert not (tmp_path / "rick.m4a").exists()
    media_requests = len(youtube.media.requests)
    result = youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert result.resumed is True
    assert len(youtube.media.requests) == media_requests
    assert sorted(path.name for path in tmp_path.iterdir()) == ["rick.m4a"]


def test_failed_downloads_keep_their_parts(tmp_path: Path) -> None:
    youtube = FakeYouTube()
    youtube.media.expired.add("https://media.test/140?c=ANDROID_VR")
    with pytest.raises(StreamForbidden):
        youtube.service().download(VIDEO_ID, tmp_path / "rick.m4a", DownloadOptions())
    assert (tmp_path / "rick.m4a.140.part").exists()
    assert (tmp_path / "rick.m4a.140.part.json").exists()
