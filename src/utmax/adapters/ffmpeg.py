"""ffmpeg, which utmax needs only to turn AAC audio into MP3."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from utmax.errors import DownloadCancelled, FFmpegFailed, FFmpegNotFound

__all__ = ["FFMPEG_ENV", "STDERR_TAIL", "FFmpeg", "Process", "Spawn", "locate_ffmpeg"]

log = logging.getLogger("utmax.download")

FFMPEG_ENV = "UTMAX_FFMPEG"
STDERR_TAIL = 2000
_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_mp3_support: dict[str, bool] = {}
_mp3_lock = threading.Lock()


class Process(Protocol):
    """The part of :class:`subprocess.Popen` utmax uses (tests pass fakes)."""

    returncode: int | None

    def communicate(self, input: Any = None, timeout: float | None = None) -> tuple[Any, Any]: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


Spawn = Callable[..., Process]


def locate_ffmpeg(
    explicit: str | os.PathLike[str] | None = None,
    *,
    environ: Mapping[str, str] = os.environ,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    """The ffmpeg to run: ``explicit``, else ``$UTMAX_FFMPEG``, else ``ffmpeg`` on ``PATH``.

    Raises:
        FFmpegNotFound: that executable does not exist.
    """
    if explicit is not None:
        name, origin = os.fspath(explicit), "the ffmpeg= argument"
    elif environ.get(FFMPEG_ENV):
        name, origin = environ[FFMPEG_ENV], f"${FFMPEG_ENV}"
    else:
        name, origin = "ffmpeg", "PATH"
    found = which(name)
    if found is None:
        raise FFmpegNotFound(
            f"ffmpeg was not found (looked for {name!r} from {origin}); "
            "it is needed only for .mp3 files."
        )
    return found


class FFmpeg:
    """One ffmpeg executable, run without a console window, stdin or terminal output."""

    def __init__(
        self, executable: str, *, spawn: Spawn = subprocess.Popen, poll_interval: float = 0.1
    ) -> None:
        self.executable = executable
        self._spawn = spawn
        self._poll = poll_interval

    def check_mp3(self) -> None:
        """Make sure this ffmpeg can write MP3 (probed once per executable).

        Raises:
            FFmpegNotFound: it cannot run, or it was built without ``libmp3lame``.
        """
        with _mp3_lock:
            supported = _mp3_support.get(self.executable)
            if supported is None:
                _, stdout, _ = self._run([self.executable, "-hide_banner", "-encoders"], None)
                supported = b"libmp3lame" in stdout
                _mp3_support[self.executable] = supported
        if not supported:
            raise FFmpegNotFound(
                f"{self.executable} cannot write MP3: it was built without libmp3lame.",
                suggestion="Install an ffmpeg build that includes libmp3lame, or download .m4a.",
            )

    def to_mp3(self, source: Path, target: Path, *, cancel: threading.Event | None = None) -> None:
        """Convert the first audio stream of ``source`` to MP3 (LAME VBR quality 2) at ``target``.

        Raises:
            FFmpegFailed: ffmpeg exited with an error; ``stderr_tail`` holds its last words.
            DownloadCancelled: ``cancel`` was set; ffmpeg was stopped.
        """
        args = [
            self.executable,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
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
            str(target),
        ]
        log.info("converting %s to MP3 with %s", source.name, self.executable)
        returncode, _, stderr = self._run(args, cancel)
        if returncode != 0:
            tail = stderr.decode("utf-8", errors="replace").strip()[-STDERR_TAIL:]
            raise FFmpegFailed(
                f"ffmpeg exited with code {returncode} while writing {target.name}.",
                returncode=returncode,
                stderr_tail=tail,
            )

    def _run(self, args: Sequence[str], cancel: threading.Event | None) -> tuple[int, bytes, bytes]:
        try:
            process = self._spawn(
                list(args),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_NO_WINDOW,
            )
        except OSError as error:
            raise FFmpegNotFound(f"Could not run {self.executable}: {error}") from error
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise DownloadCancelled(
                        "The MP3 conversion was cancelled; run the download again to finish it."
                    )
                try:
                    stdout, stderr = process.communicate(timeout=self._poll)
                except subprocess.TimeoutExpired:
                    continue
                code = process.returncode
                return (0 if code is None else code), stdout or b"", stderr or b""
        except BaseException:
            _stop(process)
            raise


def _stop(process: Process) -> None:
    """Stop a running ffmpeg, killing it when it ignores ``terminate``."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
