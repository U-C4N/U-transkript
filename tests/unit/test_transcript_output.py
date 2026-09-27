"""Tests for Transcript rendering and saving."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.builders import make_transcript
from utmax.errors import UnsupportedFormat
from utmax.models import Segment

NASTY = "♪ Ğüşiöç 日本語 😀"


@pytest.mark.parametrize(
    ("name", "fmt"), [("t.srt", "srt"), ("t.vtt", "vtt"), ("t.json", "json"), ("t.txt", "txt")]
)
def test_save_writes_utf8_without_bom_and_lf_only(tmp_path: Path, name: str, fmt: str) -> None:
    transcript = make_transcript(Segment(0, 1, NASTY), Segment(1, 1, "line one\nline two"))
    path = transcript.save(tmp_path / name)
    data = path.read_bytes()
    assert data.decode("utf-8") == transcript.to(fmt)  # type: ignore[arg-type]
    assert NASTY.encode() in data
    assert b"\r\n" not in data
    assert not data.startswith(b"\xef\xbb\xbf")


def test_save_accepts_str_paths_and_explicit_formats(tmp_path: Path) -> None:
    path = make_transcript(Segment(5, 1, "hello")).save(
        str(tmp_path / "notes.txt"), format="pretty"
    )
    assert isinstance(path, Path)
    assert path.read_text(encoding="utf-8") == "[00:05] hello\n"


def test_save_rejects_unknown_extensions_without_writing(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedFormat):
        make_transcript().save(tmp_path / "t.docx")
    assert list(tmp_path.iterdir()) == []


def test_to_methods_match_the_renderers() -> None:
    transcript = make_transcript(Segment(0, 1, "a"))
    assert transcript.to_srt() == transcript.to("srt")
    assert transcript.to_vtt() == transcript.to("vtt")
    assert transcript.to_json() == transcript.to("json")
    assert transcript.to_json(indent=None).count("\n") == 1
    assert transcript.to_text(separator="|") == "a\n"
    assert transcript.to_pretty() == transcript.to("pretty")
    with pytest.raises(UnsupportedFormat):
        transcript.to("docx")  # type: ignore[arg-type]
