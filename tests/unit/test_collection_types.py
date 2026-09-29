"""Tests for the collection and bulk models and errors."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

import utmax
from utmax import errors
from utmax.models import BulkReport, BulkResult, Transcript, VideoEntry, VideoList

FIRST = VideoEntry("PXC_PYeB6F8", "Angels On My Side", 231.0, "Rick Astley", "UC" + "x" * 22, 1)
SECOND = VideoEntry("LaOUkDBDjW8", "Dance", None, "Rick Astley", "UC" + "x" * 22, 2)


def test_video_entries_know_their_url() -> None:
    assert FIRST.url == "https://www.youtube.com/watch?v=PXC_PYeB6F8"


def test_video_lists_are_sequences_of_entries() -> None:
    videos = VideoList("Videos", "UULF" + "x" * 22, "videos", 139, (FIRST, SECOND))
    assert len(videos) == 2
    assert videos[0] is FIRST
    assert videos[-1:] == (SECOND,)
    assert [entry.video_id for entry in videos] == ["PXC_PYeB6F8", "LaOUkDBDjW8"]
    assert (videos.title, videos.kind, videos.video_count) == ("Videos", "videos", 139)


def test_bulk_reports_group_results_by_status() -> None:
    missing = errors.VideoUnavailable("gone", video_id="b")
    report: BulkReport[Transcript] = BulkReport(
        (
            BulkResult("a", "ok", path=Path("a.en.srt")),
            BulkResult("b", "failed", error=missing),
            BulkResult("c", "skipped", path=Path("c.en.srt")),
            BulkResult("d", "not_attempted"),
            BulkResult("e", "ok"),
        )
    )
    assert len(report) == 5
    assert report[1].error is missing
    assert [result.video_id for result in report.ok] == ["a", "e"]
    assert [result.video_id for result in report.failed] == ["b"]
    assert [result.video_id for result in report.skipped] == ["c"]
    assert [result.video_id for result in report.not_attempted] == ["d"]
    assert [result.video_id for result in report[3:]] == ["d", "e"]


def test_raise_for_errors_raises_the_first_failure() -> None:
    first = errors.IpBlocked("429", video_id="b")
    report: BulkReport[Transcript] = BulkReport(
        (
            BulkResult("a", "ok"),
            BulkResult("b", "failed", error=first),
            BulkResult("c", "failed", error=errors.VideoUnavailable("gone")),
        )
    )
    with pytest.raises(errors.IpBlocked) as caught:
        report.raise_for_errors()
    assert caught.value is first
    BulkReport((BulkResult("a", "ok"), BulkResult("b", "skipped"))).raise_for_errors()


@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (errors.InvalidSource, errors.UTMaxError),
        (errors.InvalidSource, ValueError),
        (errors.CollectionNotFound, errors.YouTubeError),
        (errors.CollectionUnavailable, errors.YouTubeError),
    ],
)
def test_collection_error_hierarchy(child: type[Exception], parent: type[Exception]) -> None:
    assert issubclass(child, parent)


def test_collection_error_fields() -> None:
    missing = errors.CollectionNotFound("no such playlist", source="PLx")
    assert (missing.source, missing.video_id) == ("PLx", None)
    mix = errors.CollectionUnavailable("mix", source="RDx", reason="Mixes cannot be listed.")
    assert (mix.source, mix.reason) == ("RDx", "Mixes cannot be listed.")
    assert errors.CollectionUnavailable("mix", source="RDx").reason == ""
    assert "RD" in errors.CollectionUnavailable.suggestion
    assert "@handle" in errors.InvalidSource.suggestion


@pytest.mark.parametrize(
    "error",
    [
        errors.InvalidSource("not a playlist"),
        errors.CollectionNotFound("missing", source="@nobody"),
        errors.CollectionUnavailable("mix", source="RDx", reason="unviewable"),
    ],
)
def test_collection_errors_survive_pickling(error: errors.UTMaxError) -> None:
    clone = pickle.loads(pickle.dumps(error))
    assert type(clone) is type(error)
    assert str(clone) == str(error)
    assert clone.__dict__ == error.__dict__


def test_collection_names_are_exported() -> None:
    for name in ("CollectionNotFound", "CollectionUnavailable", "InvalidSource"):
        assert name in errors.__all__
        assert name in utmax.__all__
        assert getattr(utmax, name) is getattr(errors, name)
    for name in ("BulkReport", "BulkResult", "CollectionKind", "VideoEntry", "VideoList"):
        assert name in utmax.__all__
        assert hasattr(utmax, name)
