"""Tests for the file-name templates of bulk calls."""

from __future__ import annotations

from dataclasses import replace
from fnmatch import fnmatchcase
from pathlib import Path, PurePath

import pytest

from tests.helpers.builders import VIDEO
from tests.helpers.fake_media import media_stream
from utmax.adapters import files
from utmax.adapters.downloader import Job
from utmax.adapters.files import write_text_atomic
from utmax.core.filenames import (
    MAX_BULK_NAME_BYTES,
    NameTemplate,
    glob_literal,
    part_name,
    resolve_target,
    sidecar_name,
)
from utmax.errors import InvalidOption
from utmax.models import VideoInfo

NAME_MAX = 255  # bytes in a file name on Linux and macOS
FIELDS = ("video_id", "title", "channel", "index", "language_code", "ext")
TRANSCRIPT = NameTemplate.parse("{video_id}.{language_code}.{ext}", allowed=FIELDS)
VIDEO_NAME = NameTemplate.parse("{title} [{video_id}].{ext}", allowed=FIELDS)


def test_templates_remember_their_fields() -> None:
    assert TRANSCRIPT.fields == ("video_id", "language_code", "ext")
    numbered = NameTemplate.parse("{index:03d} - {title} [{video_id}].{ext}", allowed=FIELDS)
    assert numbered.fields == ("index", "title", "video_id", "ext")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{title}.{ext}", "does not contain {video_id}"),
        ("{video_id}.{language}.{ext}", "uses {language}"),
        ("{video_id}.{title.upper}", "uses {title.upper}"),
        ("{video_id}{}", "uses {}"),
        ("{video_id", "is not a valid template"),
        ("{video_id}}", "is not a valid template"),
        ("subs/{video_id}.{ext}", "makes a path"),
        ("{video_id}\\{ext}", "makes a path"),
        ("{title:/>9} {video_id}", "makes a path"),
        ("{title}: {video_id}.{ext}", "contains ':'"),
        ("{title}|{video_id}.{ext}", "contains '|'"),
        ("{video_id}*.{ext}", "contains '*'"),
        ("{video_id}?.{ext}", "contains '?'"),
        ('{video_id}".{ext}', "contains '\"'"),
        ("{video_id}\x00.{ext}", "contains '\\x00'"),
        ("{title:*>9} {video_id}", "contains '*'"),
        ("{video_id}.{ext}.", "ends with '.'"),
        ("{video_id}{index:<3}", "ends with ' '"),
        ("{video_id}{title:{index}}", "inside a format spec"),
        ("{video_id}.{title:03d}", "cannot be filled in"),
        ("{video_id}.{title!r}", "converts {title} with !r"),
        ("{video_id!s}.{ext}", "converts {video_id} with !s"),
        ("{video_id:.5}.{ext}", "formats {video_id}"),
        ("{video_id:>12}.{ext}", "formats {video_id}"),
    ],
)
def test_bad_templates_are_refused(text: str, message: str) -> None:
    with pytest.raises(InvalidOption, match="filename=") as caught:
        NameTemplate.parse(text, allowed=FIELDS)
    assert message in str(caught.value)


def test_download_templates_have_no_language_field() -> None:
    with pytest.raises(InvalidOption, match=r"uses \{language_code\}") as caught:
        NameTemplate.parse("{video_id}.{language_code}.{ext}", allowed=("video_id", "ext"))
    assert "{ext}, {video_id}" in caught.value.suggestion


def test_render_makes_titles_channels_and_language_codes_safe() -> None:
    template = NameTemplate.parse(
        "{index:02d} {channel} - {title} [{video_id}].{language_code}.{ext}", allowed=FIELDS
    )
    name = template.render(
        {
            "video_id": "dQw4w9WgXcQ",
            "title": 'Who: "Rick"?',
            "channel": "AC/DC",
            "index": 7,
            "language_code": "en/../x",
            "ext": "srt",
        }
    )
    assert name == "07 AC_DC - Who_ _Rick__ [dQw4w9WgXcQ].en_.._x.srt"


def test_an_empty_title_becomes_the_video_id() -> None:
    values = {"video_id": "dQw4w9WgXcQ", "title": " ... ", "ext": "mp4"}
    assert VIDEO_NAME.render(values) == "dQw4w9WgXcQ [dQw4w9WgXcQ].mp4"


def test_long_names_shorten_the_title_and_keep_the_rest() -> None:
    template = NameTemplate.parse("{channel} - {title} [{video_id}].{ext}", allowed=FIELDS)
    wide = "\U00004e2d" * 100  # 300 UTF-8 bytes, cut to 60 characters (180 bytes) by safe_name
    name = template.render(
        {"video_id": "dQw4w9WgXcQ", "title": wide, "channel": wide, "ext": "mp4"}
    )
    assert len(name.encode("utf-8")) <= MAX_BULK_NAME_BYTES
    assert name.endswith(" [dQw4w9WgXcQ].mp4")
    assert name.startswith("\U00004e2d" * 60 + " - \U00004e2d")


def atomic_write_affix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    """How many bytes ``write_text_atomic`` adds to a name for the temporary file it writes."""
    temporary: list[str] = []
    replace_file = files.replace_with_retry

    def spy(source: Path, target: Path) -> None:
        temporary.append(source.name)
        replace_file(source, target)

    monkeypatch.setattr(files, "replace_with_retry", spy)
    write_text_atomic(tmp_path / "a", "")
    return len(temporary[0]) - len("a")


def test_the_longest_name_leaves_room_for_the_files_a_download_derives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = NameTemplate.parse("{channel} - {title} [{video_id}].{ext}", allowed=FIELDS)
    name = template.render(
        {"video_id": "dQw4w9WgXcQ", "title": "t" * 150, "channel": "c" * 150, "ext": "mp4"}
    )
    assert len(name) == MAX_BULK_NAME_BYTES  # ASCII: the title gave way until the name fit
    final = PurePath(name)
    job = Job(media_stream(401, "https://media.test/401", 1), Path(part_name(final, 401)))
    sidecar = sidecar_name(final, "c" * 20)
    affix = atomic_write_affix(tmp_path, monkeypatch)
    for written in (final, job.state_path, sidecar):
        assert len(written.name.encode("utf-8")) + affix <= NAME_MAX


def test_patterns_escape_what_is_known_and_match_the_rest() -> None:
    pattern = VIDEO_NAME.pattern({"video_id": "dQw4w9WgXcQ", "ext": "mp4", "title": "ignored"})
    assert pattern == "* [[]dQw4w9WgXcQ].mp4"
    assert fnmatchcase("Never Gonna [Live] [dQw4w9WgXcQ].mp4", pattern)
    assert not fnmatchcase("Never Gonna [dQw4w9WgXcQ].mp4.137.part", pattern)
    assert not fnmatchcase("Other [jNQXAC9IVRw].mp4", pattern)
    assert TRANSCRIPT.pattern({"video_id": "dQw4w9WgXcQ", "ext": "srt"}) == "dQw4w9WgXcQ.*.srt"


def test_patterns_take_extra_globs_as_they_are() -> None:
    values = {"video_id": "dQw4w9WgXcQ", "ext": "srt", "language_code": "de"}
    assert TRANSCRIPT.pattern(values) == "dQw4w9WgXcQ.de.srt"
    assert TRANSCRIPT.pattern(values, {"language_code": "de-*"}) == "dQw4w9WgXcQ.de-*.srt"
    fixed = NameTemplate.parse("[{video_id}] subtitles.txt", allowed=FIELDS)
    assert fixed.pattern({"video_id": "a"}) == "[[]a] subtitles.txt"


def test_patterns_match_any_index() -> None:
    # A new upload shifts the positions of a channel listing; the video ID keeps names unique.
    numbered = NameTemplate.parse("{index:03d} {video_id}.{ext}", allowed=FIELDS)
    pattern = numbered.pattern({"video_id": "dQw4w9WgXcQ", "index": 7, "ext": "srt"})
    assert pattern == "* dQw4w9WgXcQ.srt"
    assert fnmatchcase("012 dQw4w9WgXcQ.srt", pattern)


def test_glob_literals_match_only_themselves() -> None:
    assert glob_literal("a*b?c[d]") == "a[*]b[?]c[[]d]"
    assert fnmatchcase("a*b?c[d]", glob_literal("a*b?c[d]"))
    assert not fnmatchcase("axbycd]", glob_literal("a*b?c[d]"))


def test_folder_targets_name_files_with_a_callback() -> None:
    folder = resolve_target("videos/", format="m4a", is_dir=False)

    def name(video: VideoInfo, ext: str) -> str:
        return f"{video.video_id}.{ext}"

    assert folder.path_for(VIDEO, name=name) == PurePath("videos", "dQw4w9WgXcQ.m4a")
    assert folder.path_for(replace(VIDEO, title="")) == PurePath("videos", "dQw4w9WgXcQ.m4a")
    file = resolve_target("rick.mp4", format=None, is_dir=False)
    assert file.path_for(VIDEO, name=name) == PurePath("rick.mp4")
