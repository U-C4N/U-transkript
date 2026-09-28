"""Tests for the ffmpeg adapter with fake processes (the real ffmpeg: test_ffmpeg_mp3.py)."""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from utmax.adapters import ffmpeg as ffmpeg_module
from utmax.adapters.ffmpeg import FFMPEG_ENV, FFmpeg, locate_ffmpeg
from utmax.errors import DownloadCancelled, FFmpegFailed, FFmpegNotFound

ENCODERS = (
    b" A..... aac                  AAC (Advanced Audio Coding)\n"
    b" A..... libmp3lame           libmp3lame MP3 (MPEG audio layer 3) (codec mp3)\n"
)


class FakeProcess:
    """Enough of ``subprocess.Popen`` for the adapter."""

    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        running: int = 0,
        interrupt: bool = False,
        stubborn: bool = False,
    ) -> None:
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self._code = returncode
        self._output = (stdout, stderr)
        self._running = running
        self._interrupt = interrupt
        self._stubborn = stubborn

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes, bytes]:
        if self._interrupt:
            self._interrupt = False
            raise KeyboardInterrupt
        if self._running > 0:
            self._running -= 1
            raise subprocess.TimeoutExpired("ffmpeg", timeout or 0)
        self.returncode = self._code
        return self._output

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self._code = -15
        if not self._stubborn:
            self._running = 0

    def kill(self) -> None:
        self.killed = True
        self._running = 0


class FakeSpawn:
    """Records every command and hands out the given processes in order."""

    def __init__(self, *processes: FakeProcess | OSError) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self._processes = deque(processes)

    def __call__(self, args: list[str], **options: Any) -> FakeProcess:
        self.calls.append((args, options))
        process = self._processes.popleft()
        if isinstance(process, OSError):
            raise process
        return process


@pytest.fixture(autouse=True)
def fresh_probe_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg_module, "_mp3_support", {})


def test_locate_prefers_the_argument_then_the_environment_then_path() -> None:
    known = {
        "C:/tools/ffmpeg.exe": "C:/tools/ffmpeg.exe",
        "/opt/ff": "/opt/ff",
        "ffmpeg": "/bin/ff",
    }
    environ = {FFMPEG_ENV: "/opt/ff"}
    assert locate_ffmpeg("C:/tools/ffmpeg.exe", environ=environ, which=known.get) == (
        "C:/tools/ffmpeg.exe"
    )
    assert locate_ffmpeg(None, environ=environ, which=known.get) == "/opt/ff"
    assert locate_ffmpeg(None, environ={}, which=known.get) == "/bin/ff"
    assert locate_ffmpeg(Path("ffmpeg"), environ={}, which=known.get) == "/bin/ff"


@pytest.mark.parametrize(
    ("explicit", "environ", "origin"),
    [
        ("/nowhere/ffmpeg", {}, "the ffmpeg= argument"),
        (None, {FFMPEG_ENV: "/nowhere/ffmpeg"}, "$UTMAX_FFMPEG"),
        (None, {}, "PATH"),
    ],
)
def test_missing_ffmpeg_says_where_it_looked(
    explicit: str | None, environ: dict[str, str], origin: str
) -> None:
    with pytest.raises(FFmpegNotFound, match=r"needed only for \.mp3 files") as caught:
        locate_ffmpeg(explicit, environ=environ, which=lambda _: None)
    assert origin in str(caught.value)
    assert "winget install Gyan.FFmpeg" in caught.value.suggestion


def test_mp3_support_is_checked_once_per_executable() -> None:
    spawn = FakeSpawn(FakeProcess(stdout=ENCODERS))
    FFmpeg("ffmpeg", spawn=spawn).check_mp3()
    FFmpeg("ffmpeg", spawn=spawn).check_mp3()
    assert len(spawn.calls) == 1
    assert spawn.calls[0][0] == ["ffmpeg", "-hide_banner", "-encoders"]


def test_builds_without_lame_are_refused() -> None:
    spawn = FakeSpawn(FakeProcess(stdout=b" A..... aac  AAC (Advanced Audio Coding)\n"))
    with pytest.raises(FFmpegNotFound, match="built without libmp3lame"):
        FFmpeg("ffmpeg", spawn=spawn).check_mp3()


def test_to_mp3_runs_ffmpeg_quietly() -> None:
    spawn = FakeSpawn(FakeProcess(running=2))
    FFmpeg("/usr/bin/ffmpeg", spawn=spawn, poll_interval=0).to_mp3(Path("in.part"), Path("out.tmp"))
    args, options = spawn.calls[0]
    assert args == [
        "/usr/bin/ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-i",
        "in.part",
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        "-map_metadata",
        "-1",
        "-f",
        "mp3",
        "out.tmp",
    ]
    assert options["stdin"] is subprocess.DEVNULL
    assert options["stdout"] is subprocess.PIPE
    assert options["stderr"] is subprocess.PIPE
    assert options["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_failures_keep_the_end_of_stderr() -> None:
    noise = b"x" * 5000 + b"\nin.part: Invalid data found when processing input\n"
    spawn = FakeSpawn(FakeProcess(returncode=1, stderr=noise))
    with pytest.raises(FFmpegFailed, match="exited with code 1") as caught:
        FFmpeg("ffmpeg", spawn=spawn).to_mp3(Path("in.part"), Path("out.tmp"))
    assert caught.value.returncode == 1
    assert caught.value.stderr_tail.endswith("Invalid data found when processing input")
    assert len(caught.value.stderr_tail) == 2000


def test_cancel_stops_ffmpeg() -> None:
    process = FakeProcess(running=1000)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled, match="cancelled"):
        FFmpeg("ffmpeg", spawn=FakeSpawn(process), poll_interval=0).to_mp3(
            Path("a"), Path("b"), cancel=cancel
        )
    assert process.terminated
    assert not process.killed


def test_ffmpeg_that_ignores_terminate_is_killed() -> None:
    process = FakeProcess(running=1000, stubborn=True)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DownloadCancelled):
        FFmpeg("ffmpeg", spawn=FakeSpawn(process), poll_interval=0).to_mp3(
            Path("a"), Path("b"), cancel=cancel
        )
    assert process.killed


def test_ctrl_c_stops_ffmpeg_and_propagates() -> None:
    process = FakeProcess(interrupt=True)
    with pytest.raises(KeyboardInterrupt):
        FFmpeg("ffmpeg", spawn=FakeSpawn(process)).to_mp3(Path("a"), Path("b"))
    assert process.terminated


def test_executables_that_cannot_start_count_as_missing() -> None:
    with pytest.raises(FFmpegNotFound, match="Could not run"):
        FFmpeg("ffmpeg", spawn=FakeSpawn(PermissionError("denied"))).to_mp3(Path("a"), Path("b"))
