"""Tests for the download models and errors."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

import utmax
from tests.helpers.builders import VIDEO
from utmax import errors
from utmax.models import DownloadResult, Format, Progress

H264 = Format(137, "video", "mp4", "h264", "avc1.640028", 1920, 1080, 25, 4334157, 80911999)
AAC = Format(
    140,
    "audio",
    "mp4",
    "aac",
    "mp4a.40.2",
    bitrate=130677,
    content_length=3449447,
    audio_sample_rate=44100,
    audio_channels=2,
)
HE_AAC_DRC = Format(
    139, "audio", "mp4", "he-aac", "mp4a.40.5", audio_sample_rate=22050, is_drc=True
)


@pytest.mark.parametrize(
    ("fmt", "label"),
    [
        (H264, "137 mp4 h264 1080p25"),
        (Format(248, "video", "webm", "vp9", "vp9", 1080, 1920, 30), "248 webm vp9 1080p30"),
        (Format(160, "video", "mp4", "h264", "avc1.4d400c", height=144), "160 mp4 h264 144p"),
        (AAC, "140 mp4 aac 44.1kHz"),
        (HE_AAC_DRC, "139 mp4 he-aac 22.05kHz drc"),
        (Format(251, "audio", "webm", "opus", "opus"), "251 webm opus"),
    ],
)
def test_format_labels(fmt: Format, label: str) -> None:
    assert fmt.label == label


def test_progress_fraction() -> None:
    assert Progress("v", "downloading", 50, 200).fraction == 0.25
    assert Progress("v", "downloading", 250, 200).fraction == 1.0
    assert Progress("v", "converting", 0, None).fraction is None
    assert Progress("v", "downloading", 0, 0).fraction is None


def test_download_result_defaults() -> None:
    result = DownloadResult(Path("rick.m4a"), VIDEO, "m4a", None, AAC)
    assert result.embedded_subtitles == ()
    assert result.sidecars == ()
    assert (result.size_bytes, result.resumed) == (0, False)


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (errors.FormatNotAvailable, errors.DownloadError),
        (errors.StreamForbidden, errors.DownloadError),
        (errors.DownloadIncomplete, errors.DownloadError),
        (errors.DownloadCancelled, errors.DownloadError),
        (errors.OutputExists, errors.DownloadError),
        (errors.MuxError, errors.DownloadError),
        (errors.FFmpegError, errors.DownloadError),
        (errors.FFmpegNotFound, errors.FFmpegError),
        (errors.FFmpegFailed, errors.FFmpegError),
    ],
)
def test_download_error_hierarchy(child: type[Exception], parent: type[Exception]) -> None:
    assert issubclass(child, parent)


def test_download_error_fields() -> None:
    missing = errors.FormatNotAvailable("none", available=["137 mp4 h264 1080p25"], video_id="v")
    assert (missing.available, missing.video_id) == (("137 mp4 h264 1080p25",), "v")
    assert errors.StreamForbidden("403", itag=137).itag == 137
    failed = errors.FFmpegFailed("bad", returncode=1, stderr_tail="Invalid data")
    assert (failed.returncode, failed.stderr_tail) == (1, "Invalid data")
    assert "winget install Gyan.FFmpeg" in errors.FFmpegNotFound.suggestion
    assert errors.OutputExists("exists").suggestion.startswith("Pass overwrite=True")


@pytest.mark.parametrize(
    "error",
    [
        errors.FormatNotAvailable("none", available=["18 mp4 h264 360p25"], video_id="v"),
        errors.StreamForbidden("403", itag=401, video_id="v"),
        errors.DownloadIncomplete("short", video_id="v"),
        errors.DownloadCancelled("stopped", video_id="v"),
        errors.OutputExists("exists", suggestion="Pick another name."),
        errors.FFmpegError("broken"),
        errors.FFmpegNotFound("missing"),
        errors.FFmpegFailed("exit 1", returncode=1, stderr_tail="tail", video_id="v"),
    ],
)
def test_download_errors_survive_pickling(error: errors.UTMaxError) -> None:
    clone = pickle.loads(pickle.dumps(error))
    assert type(clone) is type(error)
    assert str(clone) == str(error)
    assert clone.__dict__ == error.__dict__


def test_download_names_are_exported() -> None:
    for name in (
        "DownloadCancelled",
        "DownloadIncomplete",
        "FFmpegError",
        "FFmpegFailed",
        "FFmpegNotFound",
        "FormatNotAvailable",
        "OutputExists",
        "StreamForbidden",
    ):
        assert name in errors.__all__
        assert name in utmax.__all__
        assert getattr(utmax, name) is getattr(errors, name)
    for name in ("Container", "DownloadResult", "Format", "Progress"):
        assert name in utmax.__all__
        assert hasattr(utmax, name)
