"""Filesystem helpers: atomic text writes that tolerate Windows file locks."""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path

__all__ = ["REPLACE_RETRY_DELAYS", "replace_with_retry", "write_text_atomic"]

REPLACE_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)


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
