"""Tests for fetch_many and translate_many over a fake YouTube with several videos."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.helpers.bulk import IDS, TITLES, ManyVideos
from tests.helpers.fake_translator import FakeTranslator
from utmax.errors import (
    InvalidModelSpec,
    InvalidOption,
    InvalidVideoId,
    IpBlocked,
    ProviderAuthError,
    UnsupportedFormat,
    UTMaxError,
    VideoUnavailable,
)
from utmax.models import BulkResult, Transcript
from utmax.services.bulk import BulkService


def value(result: BulkResult[Transcript]) -> Transcript:
    assert result.value is not None
    return result.value


def test_fetch_many_returns_transcripts_in_input_order() -> None:
    report = ManyVideos().bulk().fetch_many(IDS)
    assert [result.status for result in report] == ["ok", "ok", "ok"]
    assert [value(result).video.title for result in report] == [TITLES[i] for i in IDS]
    assert [value(result).language_code for result in report] == ["en", "en", "en"]
    assert [result.path for result in report] == [None, None, None]


def test_fetch_many_saves_files_named_by_the_template(tmp_path: Path) -> None:
    subs = tmp_path / "subs"
    report = ManyVideos().bulk().fetch_many(IDS[:2], out_dir=subs)
    assert [result.path for result in report] == [subs / f"{i}.en.srt" for i in IDS[:2]]
    text = (subs / f"{IDS[0]}.en.srt").read_text(encoding="utf-8")
    assert text.startswith("1\n00:00:01,360 --> 00:00:03,040\n")
    pretty = (
        ManyVideos()
        .bulk()
        .fetch_many(
            IDS[:1],
            out_dir=subs,
            format="pretty",
            filename="{index:02d} {title} [{video_id}].{ext}",
        )
    )
    assert pretty[0].path == subs / f"01 {TITLES[IDS[0]]} [{IDS[0]}].txt"
    assert pretty[0].path.read_text(encoding="utf-8").startswith("[00:01] ")


def test_existing_files_are_skipped_without_a_request(tmp_path: Path) -> None:
    old = tmp_path / f"{IDS[0]}.en.srt"
    old.write_text("old", encoding="utf-8")
    youtube = ManyVideos()
    report = youtube.bulk().fetch_many(IDS[:2], out_dir=tmp_path)
    assert [(result.status, result.path) for result in report] == [
        ("skipped", old),
        ("ok", tmp_path / f"{IDS[1]}.en.srt"),
    ]
    assert youtube.players == [IDS[1]]
    assert old.read_text(encoding="utf-8") == "old"
    again = youtube.bulk().fetch_many(IDS[:2], out_dir=tmp_path, skip_existing=False)
    assert [result.status for result in again] == ["ok", "ok"]
    assert old.read_text(encoding="utf-8") != "old"


@pytest.mark.parametrize(
    ("existing", "languages", "skipped"),
    [
        ("en", None, True),
        ("en", ["de"], False),
        ("en", ["en"], True),
        ("de-DE", ["de"], True),
        ("de-DE", "de", True),
        ("de", ["de-AT"], True),
        ("en", ["de", "en"], True),
    ],
)
def test_the_requested_languages_decide_which_files_count(
    tmp_path: Path, existing: str, languages: list[str] | str | None, skipped: bool
) -> None:
    (tmp_path / f"{IDS[0]}.{existing}.srt").write_text("old", encoding="utf-8")
    report = ManyVideos().bulk().fetch_many(IDS[:1], out_dir=tmp_path, languages=languages)
    assert (report[0].status == "skipped") is skipped


def test_failures_are_reported_per_video() -> None:
    youtube = ManyVideos(missing={IDS[1]})
    report = youtube.bulk().fetch_many([IDS[0], IDS[1], "not a video", IDS[2]])
    assert [result.status for result in report] == ["ok", "failed", "failed", "ok"]
    assert isinstance(report[1].error, VideoUnavailable)
    assert isinstance(report[2].error, InvalidVideoId)
    with pytest.raises(VideoUnavailable):
        report.raise_for_errors()


def test_a_block_stops_fetch_many() -> None:
    youtube = ManyVideos(blocked={IDS[1]})
    report = youtube.bulk().fetch_many(IDS, concurrency=1)
    assert [result.status for result in report] == ["ok", "failed", "not_attempted"]
    assert isinstance(report[1].error, IpBlocked)
    assert youtube.players == IDS[:2]


def test_progress_sees_every_video_once() -> None:
    seen: list[BulkResult[Transcript]] = []
    ManyVideos().bulk().fetch_many([*IDS, "nope"], progress=seen.append)
    assert sorted(result.video_id for result in seen) == sorted([*IDS, "nope"])


def test_translate_many_names_files_by_the_target_language(tmp_path: Path) -> None:
    bulk = ManyVideos().bulk()
    report = bulk.translate_many(IDS[:2], "tr", model=FakeTranslator(), out_dir=tmp_path)
    assert [result.path for result in report] == [tmp_path / f"{i}.tr.srt" for i in IDS[:2]]
    turkish = value(report[0])
    assert (turkish.language_code, turkish.translated_from, turkish.translator) == (
        "tr",
        "en",
        "fake=echo-1",
    )
    assert turkish.source is not None
    assert [cue.text for cue in turkish] == [cue.text.upper() for cue in turkish.source]


def test_translate_many_can_write_bilingual_subtitles(tmp_path: Path) -> None:
    bulk = ManyVideos().bulk()
    report = bulk.translate_many(
        IDS[:1], "tr", model=FakeTranslator(), out_dir=tmp_path, bilingual=True, format="vtt"
    )
    assert report[0].path == tmp_path / f"{IDS[0]}.en+tr.vtt"
    both = value(report[0])
    assert both.language_code == "en+tr"
    first, second = both.segments[1].text.split("\n")
    assert second == first.upper()


def test_translate_many_skips_what_it_would_write(tmp_path: Path) -> None:
    (tmp_path / f"{IDS[0]}.tr.srt").write_text("old", encoding="utf-8")
    (tmp_path / f"{IDS[1]}.en+tr.srt").write_text("old", encoding="utf-8")
    translator = FakeTranslator()
    bulk = ManyVideos().bulk()
    plain = bulk.translate_many(IDS[:2], "tr", model=translator, out_dir=tmp_path)
    assert [result.status for result in plain] == ["skipped", "ok"]
    both = bulk.translate_many(IDS, "tr", model=translator, out_dir=tmp_path, bilingual=True)
    assert [result.status for result in both] == ["ok", "skipped", "ok"]


def test_a_rejected_api_key_stops_translate_many() -> None:
    def reject(request: dict[str, Any]) -> str:
        raise ProviderAuthError("The API key was rejected.", provider="fake")

    bulk = ManyVideos().bulk()
    report = bulk.translate_many(IDS, "tr", model=FakeTranslator(reject), concurrency=1)
    assert [result.status for result in report] == ["failed", "not_attempted", "not_attempted"]
    assert isinstance(report[0].error, ProviderAuthError)


Call = Callable[[BulkService, Path], object]


@pytest.mark.parametrize(
    ("call", "error"),
    [
        (lambda bulk, folder: bulk.fetch_many(IDS, out_dir=folder, concurrency=0), InvalidOption),
        (
            lambda bulk, folder: bulk.fetch_many(IDS, out_dir=folder, format="doc"),
            UnsupportedFormat,
        ),
        (
            lambda bulk, folder: bulk.fetch_many(IDS, out_dir=folder, filename="{title}.{ext}"),
            InvalidOption,
        ),
        (lambda bulk, folder: bulk.fetch_many(IDS[0], out_dir=folder), InvalidOption),
        (
            lambda bulk, folder: bulk.translate_many(IDS, "not a code", model=FakeTranslator()),
            InvalidOption,
        ),
        (
            lambda bulk, folder: bulk.translate_many(IDS, "tr", model=FakeTranslator(), key="x"),
            InvalidOption,
        ),
        (
            lambda bulk, folder: bulk.translate_many(IDS, "tr", model="nope=model-1"),
            InvalidModelSpec,
        ),
    ],
)
def test_bad_arguments_fail_before_any_request(
    tmp_path: Path, call: Call, error: type[UTMaxError]
) -> None:
    youtube = ManyVideos()
    folder = tmp_path / "subs"
    with pytest.raises(error):
        call(youtube.bulk(), folder)
    assert youtube.players == []
    assert not folder.exists()


def test_out_dir_must_be_a_folder(tmp_path: Path) -> None:
    file = tmp_path / "file.txt"
    file.write_text("x", encoding="utf-8")
    with pytest.raises(InvalidOption, match="is a file, not a folder"):
        ManyVideos().bulk().fetch_many(IDS, out_dir=file)
