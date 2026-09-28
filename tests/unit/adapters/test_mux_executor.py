"""Tests for writing mux plans to disk and reading inputs from files."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.fmp4_factory import Sample, Track, simple_file
from utmax.adapters import files
from utmax.adapters.files import COPY_BLOCK_SIZE, FileByteSource, write_mux_plan
from utmax.core.media.boxes import ByteSource, BytesSource
from utmax.core.media.mux import Blob, CopyOp, MuxPlan, PlanSource, plan_mux
from utmax.errors import MuxError


class RecordingSource:
    def __init__(self, data: bytes) -> None:
        self._inner = BytesSource(data)
        self.size = len(data)
        self.reads: list[tuple[int, int]] = []

    def read(self, offset: int, n: int) -> bytes:
        self.reads.append((offset, n))
        return self._inner.read(offset, n)


def test_file_byte_source_reads_ranges(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4.part"
    path.write_bytes(b"0123456789")
    with FileByteSource(path) as source:
        assert source.size == 10
        assert source.read(3, 4) == b"3456"
        assert source.read(8, 10) == b"89"
        assert source.path == path


def test_writes_exactly_the_planned_bytes(tmp_path: Path) -> None:
    video = simple_file([Sample(512, 700 + i, sync=i == 0) for i in range(30)])
    audio = simple_file(
        [Sample(1024, 90 + i) for i in range(40)],
        track=Track(handler="soun", codec="mp4a", timescale=44100),
    )
    (tmp_path / "v.part").write_bytes(video)
    (tmp_path / "a.part").write_bytes(audio)
    with FileByteSource(tmp_path / "v.part") as v, FileByteSource(tmp_path / "a.part") as a:
        plan = plan_mux([v, a], flavor="mp4")
        target = write_mux_plan(plan, [v, a], tmp_path / "out" / "video.mp4")
        expected = PlanSource(plan, [v, a]).read(0, plan.size)
    assert target == tmp_path / "out" / "video.mp4"
    assert target.read_bytes() == expected
    assert sorted(child.name for child in target.parent.iterdir()) == ["video.mp4"]


def test_copies_stream_in_blocks_and_report_progress(tmp_path: Path) -> None:
    source = RecordingSource(bytes(range(256)) * 10_000)  # 2.56 MB
    plan = MuxPlan((Blob(b"head"), CopyOp(0, 100, 2_500_000), Blob(b"tail")))
    calls: list[tuple[int, int]] = []
    write_mux_plan(plan, [source], tmp_path / "out.bin", progress=lambda d, t: calls.append((d, t)))
    assert all(n <= COPY_BLOCK_SIZE for _, n in source.reads)
    assert source.reads == [(100, 1 << 20), (100 + (1 << 20), 1 << 20), (100 + (2 << 20), 402_848)]
    assert [done for done, _ in calls] == [4, 4 + (1 << 20), 4 + (2 << 20), 2_500_004, 2_500_008]
    assert {total for _, total in calls} == {2_500_008}
    assert (tmp_path / "out.bin").read_bytes() == b"head" + source.read(100, 2_500_000) + b"tail"


def test_existing_files_are_replaced_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "out.m4a"
    target.write_bytes(b"old")
    replaced: list[tuple[Path, Path]] = []
    original = files.replace_with_retry

    def recording(source: Path, destination: Path) -> None:
        replaced.append((source, destination))
        original(source, destination)

    monkeypatch.setattr(files, "replace_with_retry", recording)
    write_mux_plan(MuxPlan((Blob(b"new"),)), [], target)
    assert target.read_bytes() == b"new"
    assert replaced[0][1] == target
    assert replaced[0][0].name.startswith(".out.m4a.")


def test_a_truncated_input_fails_and_leaves_nothing_behind(tmp_path: Path) -> None:
    target = tmp_path / "out.mp4"
    target.write_bytes(b"keep me")
    short: list[ByteSource] = [BytesSource(b"only ten b")]
    with pytest.raises(MuxError, match="ends early"):
        write_mux_plan(MuxPlan((Blob(b"x"), CopyOp(0, 0, 50))), short, target)
    assert target.read_bytes() == b"keep me"
    assert [child.name for child in tmp_path.iterdir()] == ["out.mp4"]
