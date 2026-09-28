"""Safe file names, and where ``download(video, path)`` writes its files."""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath

from utmax.errors import InvalidOption, UnsupportedFormat
from utmax.models import Container, VideoInfo

__all__ = [
    "MAX_NAME_BYTES",
    "MAX_NAME_CHARS",
    "Target",
    "default_filename",
    "part_name",
    "resolve_target",
    "safe_name",
    "sidecar_name",
]

MAX_NAME_CHARS = 150
MAX_NAME_BYTES = 180
_SUFFIXES: dict[str, Container] = {".mp4": "mp4", ".mov": "mov", ".m4a": "m4a", ".mp3": "mp3"}
_WHITESPACE = re.compile(r"\s+")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"{name}{n}" for name in ("COM", "LPT") for n in range(1, 10)}
)


def safe_name(
    text: str, *, max_chars: int = MAX_NAME_CHARS, max_bytes: int = MAX_NAME_BYTES
) -> str:
    """``text`` made safe as (part of) a file name on Windows, macOS and Linux.

    Accents are composed (NFC); runs of whitespace become one space; ``<>:"/\\|?*`` and other
    control characters become ``_``; leading and trailing dots and spaces go; the result is cut
    to ``max_chars`` characters and ``max_bytes`` UTF-8 bytes (Linux allows 255 bytes per name,
    the rest is left for suffixes); Windows device names such as ``CON`` or ``com1.txt`` get a
    leading ``_``. The result may be empty.
    """
    text = unicodedata.normalize("NFC", text)
    text = _FORBIDDEN.sub("_", _WHITESPACE.sub(" ", text))
    text = _shorten(text.strip(". "), max_chars, max_bytes).strip(". ")
    if text.split(".", maxsplit=1)[0].upper() in _DEVICE_NAMES:
        text = f"_{text}"
    return text


def default_filename(video: VideoInfo, ext: str) -> str:
    """``"{title} [{video_id}].{ext}"`` with a safe title; ``"{video_id}.{ext}"`` without one."""
    title = safe_name(video.title)
    return f"{title} [{video.video_id}].{ext}" if title else f"{video.video_id}.{ext}"


@dataclass(frozen=True, slots=True)
class Target:
    """Where a download goes: the caller's file name, or a folder plus the video's title."""

    container: Container
    file: PurePath | None = None
    folder: PurePath | None = None

    def path_for(self, video: VideoInfo) -> PurePath:
        """The output file for ``video``."""
        if self.file is not None:
            return self.file
        return (self.folder or PurePath(".")) / default_filename(video, self.container)


def resolve_target(
    path: str | os.PathLike[str], *, format: Container | None, is_dir: bool
) -> Target:
    """Decide the container and output name of ``download(video, path, format=...)``.

    ``path`` is a folder when ``is_dir`` (it exists as a directory), when it is empty, or when
    it ends with a path separator; the file is then named ``"{title} [{video_id}].{ext}"``
    inside it and the container is ``format`` (default ``"mp4"``). Otherwise the extension
    picks the container; ``format`` must agree with it, and is appended when ``path`` has no
    known extension.

    Raises:
        InvalidOption: ``format`` is unknown or contradicts the extension.
        UnsupportedFormat: the extension is not .mp4, .mov, .m4a or .mp3 and no format was given.
    """
    if format is not None and format not in _SUFFIXES.values():
        raise InvalidOption(
            f"format={format!r} is not a download format; use mp4, mov, m4a or mp3.",
            suggestion='Pass format="mp4", "mov", "m4a" or "mp3", or leave it out.',
        )
    text = os.fspath(path)
    pure = PurePath(text)
    if is_dir or not pure.name or text.endswith(("/", "\\")):
        return Target(format or "mp4", folder=pure)
    container = _SUFFIXES.get(pure.suffix.lower())
    if container is None:
        if format is None:
            raise UnsupportedFormat(
                f"Cannot tell the file type from {pure.name!r}.",
                suggestion=(
                    'Use a .mp4, .mov, .m4a or .mp3 file name or a folder, or pass format="mp4".'
                ),
            )
        return Target(format, file=pure.with_name(f"{pure.name}.{format}"))
    if format is not None and format != container:
        raise InvalidOption(
            f"format={format!r} does not match the file name {pure.name!r}.",
            suggestion="Leave format out, or give the file the matching extension.",
        )
    return Target(container, file=pure)


def sidecar_name(media: PurePath, language_code: str) -> PurePath:
    """``rick.mp4`` + ``"tr"`` gives ``rick.tr.srt``; ``"en+tr"`` gives ``rick.en+tr.srt``."""
    code = safe_name(language_code, max_chars=35, max_bytes=35)
    return media.with_name(f"{media.stem}.{code}.srt")


def part_name(target: PurePath, itag: int) -> PurePath:
    """Where stream ``itag`` of ``target`` is downloaded: ``rick.mp4`` gives ``rick.mp4.137.part``."""
    return target.with_name(f"{target.name}.{itag}.part")


def _shorten(text: str, max_chars: int, max_bytes: int) -> str:
    text = text[:max_chars]
    while len(text.encode("utf-8")) > max_bytes:
        text = text[:-1]
    return text
