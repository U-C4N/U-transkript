"""Filesystem helpers: atomic writes that tolerate Windows file locks, and muxer output."""

from __future__ import annotations

import io
import os
import secrets
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Self

from utmax.core.media.boxes import ByteSource, read_exact
from utmax.core.media.mux import Blob, CopyOp, MuxPlan

__all__ = [
    "COPY_BLOCK_SIZE",
    "REPLACE_RETRY_DELAYS",
    "FileByteSource",
    "replace_with_retry",
    "write_mux_plan",
    "write_text_atomic",
]

REPLACE_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)
COPY_BLOCK_SIZE = 1 << 20


def write_text_atomic(path: str | os.PathLike[str], text: str) -> Path:
    """Write ``text`` as UTF-8 with ``\\n`` newlines; readers never see a half-written file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def replace_with_retry(
    source: Path,
    target: Path,
    *,
    replace: Callable[[Path, Path], None] = os.replace,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """``os.replace`` that retries while antivirus or indexers briefly hold the file (Windows)."""
    for delay in REPLACE_RETRY_DELAYS:
        try:
            replace(source, target)
        except PermissionError:
            sleep(delay)
        else:
            return
    replace(source, target)


class FileByteSource:
    """A :class:`~utmax.core.media.boxes.ByteSource` over a file on disk; not thread-safe."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._handle: io.BufferedReader = self.path.open("rb")
        self.size = os.fstat(self._handle.fileno()).st_size

    def read(self, offset: int, n: int) -> bytes:
        self._handle.seek(offset)
        return self._handle.read(n)

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def write_mux_plan(
    plan: MuxPlan,
    sources: Sequence[ByteSource],
    path: str | os.PathLike[str],
    *,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Write the file ``plan`` describes to ``path`` and return ``path``.

    Copies stream in 1 MiB blocks into a temporary file next to ``path``, which is flushed to
    disk and then atomically replaces ``path`` (retrying while Windows holds a lock); on any
    error the temporary file is removed. ``progress(written, total)`` runs after each block.

    Raises:
        MuxError: an input is shorter than the plan expects.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    total = plan.size
    written = 0
    try:
        with temporary.open("xb") as handle:
            for op in plan.ops:
                for block in _blocks(op, sources):
                    handle.write(block)
                    written += len(block)
                    if progress is not None:
                        progress(written, total)
            handle.flush()
            os.fsync(handle.fileno())
        replace_with_retry(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def _blocks(op: CopyOp | Blob, sources: Sequence[ByteSource]) -> Iterator[bytes]:
    if isinstance(op, Blob):
        yield op.data
        return
    end = op.offset + op.size
    for start in range(op.offset, end, COPY_BLOCK_SIZE):
        yield read_exact(sources[op.source], start, min(COPY_BLOCK_SIZE, end - start))
