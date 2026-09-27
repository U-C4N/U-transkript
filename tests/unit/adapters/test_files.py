"""Tests for atomic file writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from utmax.adapters import files
from utmax.adapters.files import REPLACE_RETRY_DELAYS, replace_with_retry, write_text_atomic


def test_writes_utf8_with_lf_and_creates_parent_directories(tmp_path: Path) -> None:
    path = write_text_atomic(tmp_path / "sub" / "out.txt", "a\nb ♪\n")
    assert path == tmp_path / "sub" / "out.txt"
    assert path.read_bytes() == "a\nb ♪\n".encode()
    assert [child.name for child in path.parent.iterdir()] == ["out.txt"]


def test_replaces_existing_files(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    write_text_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_failed_writes_leave_no_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(source: Path, target: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(files, "replace_with_retry", broken)
    with pytest.raises(OSError, match="disk full"):
        write_text_atomic(tmp_path / "out.txt", "x")
    assert list(tmp_path.iterdir()) == []


def test_replace_waits_out_transient_locks(tmp_path: Path) -> None:
    attempts: list[Path] = []

    def flaky(source: Path, target: Path) -> None:
        attempts.append(source)
        if len(attempts) < 3:
            raise PermissionError("locked")

    sleeps: list[float] = []
    replace_with_retry(tmp_path / "a", tmp_path / "b", replace=flaky, sleep=sleeps.append)
    assert len(attempts) == 3
    assert sleeps == [0.1, 0.2]


def test_replace_gives_up_after_the_last_delay(tmp_path: Path) -> None:
    def locked(source: Path, target: Path) -> None:
        raise PermissionError("locked")

    sleeps: list[float] = []
    with pytest.raises(PermissionError):
        replace_with_retry(tmp_path / "a", tmp_path / "b", replace=locked, sleep=sleeps.append)
    assert sleeps == list(REPLACE_RETRY_DELAYS)
