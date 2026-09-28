"""Tests for safe file names and download targets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePath

import pytest

from tests.helpers.builders import VIDEO
from utmax.core.filenames import (
    MAX_NAME_BYTES,
    Target,
    default_filename,
    part_name,
    resolve_target,
    safe_name,
    sidecar_name,
)
from utmax.errors import InvalidOption, UnsupportedFormat
from utmax.models import Container

TITLE = "Rick Astley - Never Gonna Give You Up (Official Video)"
TURKISH = "\xc7ok g\xfczel \U0000015fark\U00000131 \U0001f3b5"


@pytest.mark.parametrize(
    ("text", "safe"),
    [
        (TITLE, TITLE),
        ("AC/DC: Live at River Plate", "AC_DC_ Live at River Plate"),
        ('a<b>c"d|e?f*g\\h', "a_b_c_d_e_f_g_h"),
        ("tabs\tand\nnew  lines", "tabs and new lines"),
        ("\x00bell\x07", "_bell_"),
        ("  Ends with dots...  ", "Ends with dots"),
        ("...", ""),
        ("", ""),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("com1", "_com1"),
        ("Concert", "Concert"),
        (TURKISH, TURKISH),
        ("Cafe\U00000301", "Caf\xe9"),
    ],
)
def test_safe_name(text: str, safe: str) -> None:
    assert safe_name(text) == safe


@pytest.mark.parametrize(
    ("text", "length"),
    [("a" * 300, 150), ("\U0001f3b5" * 100, 45), ("\U0000015f" * 150, 90)],
)
def test_long_names_are_cut_by_characters_and_bytes(text: str, length: int) -> None:
    safe = safe_name(text)
    assert len(safe) == length
    assert len(safe.encode("utf-8")) <= MAX_NAME_BYTES


def test_cutting_never_leaves_a_trailing_dot_or_space() -> None:
    assert safe_name("a" * 149 + ". tail") == "a" * 149


def test_default_filename() -> None:
    assert default_filename(VIDEO, "mp4") == f"{TITLE} [dQw4w9WgXcQ].mp4"
    assert default_filename(replace(VIDEO, title="AC/DC?"), "mp3") == "AC_DC_ [dQw4w9WgXcQ].mp3"
    assert default_filename(replace(VIDEO, title=" ... "), "m4a") == "dQw4w9WgXcQ.m4a"


@pytest.mark.parametrize(
    ("path", "fmt", "is_dir", "expected"),
    [
        ("rick.mp4", None, False, Target("mp4", file=PurePath("rick.mp4"))),
        ("RICK.MOV", None, False, Target("mov", file=PurePath("RICK.MOV"))),
        ("song.mp3", "mp3", False, Target("mp3", file=PurePath("song.mp3"))),
        ("rick", "m4a", False, Target("m4a", file=PurePath("rick.m4a"))),
        ("My.Video", "mp4", False, Target("mp4", file=PurePath("My.Video.mp4"))),
        ("downloads/", None, False, Target("mp4", folder=PurePath("downloads"))),
        ("downloads", "m4a", True, Target("m4a", folder=PurePath("downloads"))),
        ("", None, False, Target("mp4", folder=PurePath("."))),
    ],
)
def test_resolve_target(path: str, fmt: Container | None, is_dir: bool, expected: Target) -> None:
    assert resolve_target(path, format=fmt, is_dir=is_dir) == expected


@pytest.mark.parametrize(
    ("path", "fmt", "error", "match"),
    [
        ("notes.txt", None, UnsupportedFormat, "Cannot tell the file type"),
        ("song.mp3", "m4a", InvalidOption, "does not match the file name"),
        ("video.mp4", "avi", InvalidOption, "is not a download format"),
    ],
)
def test_bad_targets(path: str, fmt: str | None, error: type[Exception], match: str) -> None:
    with pytest.raises(error, match=match):
        resolve_target(path, format=fmt, is_dir=False)


def test_folder_targets_are_named_after_the_video() -> None:
    target = resolve_target("out/", format="mp3", is_dir=False)
    assert target.path_for(VIDEO) == PurePath("out") / f"{TITLE} [dQw4w9WgXcQ].mp3"
    assert Target("mp4", file=PurePath("x.mp4")).path_for(VIDEO) == PurePath("x.mp4")


def test_sidecar_and_part_names() -> None:
    media = PurePath("out") / "rick.mp4"
    assert sidecar_name(media, "tr") == PurePath("out") / "rick.tr.srt"
    assert sidecar_name(media, "en+tr") == PurePath("out") / "rick.en+tr.srt"
    assert part_name(media, 137) == PurePath("out") / "rick.mp4.137.part"
