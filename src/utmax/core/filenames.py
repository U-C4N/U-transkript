"""Safe file names, where ``download(video, path)`` writes its files, and the name templates
of bulk calls."""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import PurePath
from string import Formatter

from utmax.errors import InvalidOption, UnsupportedFormat
from utmax.models import Container, VideoInfo

__all__ = [
    "MAX_BULK_NAME_BYTES",
    "MAX_NAME_BYTES",
    "MAX_NAME_CHARS",
    "NameTemplate",
    "Target",
    "default_filename",
    "glob_literal",
    "part_name",
    "resolve_target",
    "safe_name",
    "sidecar_name",
]

MAX_NAME_CHARS = 150
MAX_NAME_BYTES = 180
# The most a bulk name may take, in UTF-8 bytes. Linux and macOS allow 255 per file name, and a
# download derives longer names: the temporary file of its state, "<name>.401.part.json" written
# through write_text_atomic (".<...>.<8 hex digits>.tmp"), is 28 bytes longer than the name, and
# that of a subtitle sidecar is 15 bytes plus the language code longer (255 for 20 characters).
MAX_BULK_NAME_BYTES = 220
_SUFFIXES: dict[str, Container] = {".mp4": "mp4", ".mov": "mov", ".m4a": "m4a", ".mp3": "mp3"}
_WHITESPACE = re.compile(r"\s+")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_GLOB_MAGIC = re.compile(r"([*?[])")
_SAMPLE_FIELDS: dict[str, str | int] = {
    "video_id": "dQw4w9WgXcQ",
    "title": "Title",
    "channel": "Channel",
    "index": 1,
    "language_code": "en",
    "ext": "srt",
}
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

    def path_for(
        self, video: VideoInfo, *, name: Callable[[VideoInfo, str], str] | None = None
    ) -> PurePath:
        """The output file for ``video``; in a folder, ``name(video, extension)`` replaces the
        default ``"{title} [{video_id}].{ext}"``."""
        if self.file is not None:
            return self.file
        if name is None:
            return (self.folder or PurePath(".")) / default_filename(video, self.container)
        return (self.folder or PurePath(".")) / name(video, self.container)


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


@dataclass(frozen=True, slots=True)
class NameTemplate:
    """The file-name template of a bulk call, such as ``"{title} [{video_id}].{ext}"``.

    Fields are written like :meth:`str.format` fields and may carry a format spec
    (``{index:03d}``). ``title``, ``channel`` and ``language_code`` values are made safe with
    :func:`safe_name`; an empty title becomes the video ID.
    """

    text: str
    fields: tuple[str, ...]

    @classmethod
    def parse(cls, text: str, *, allowed: Collection[str]) -> NameTemplate:
        """Check ``text``: it must contain ``{video_id}`` (every video needs its own name), use
        only ``allowed`` fields, and give a plain file name that Windows accepts too: no path
        separator, none of ``<>:"|?*`` or a control character (the fill of a format spec
        counts), and no trailing dot or space.

        Raises:
            InvalidOption: ``text`` breaks one of these rules or is not a valid template.
        """
        names = ", ".join(f"{{{field}}}" for field in sorted(allowed))
        try:
            parsed = list(Formatter().parse(text))
        except ValueError as error:
            raise InvalidOption(
                f"filename={text!r} is not a valid template: {error}.",
                suggestion=f"Write fields in braces; available fields: {names}.",
            ) from None
        fields = tuple(field for _, field, _, _ in parsed if field is not None)
        unknown = [field for field in fields if field not in allowed]
        if unknown:
            raise InvalidOption(
                f"filename={text!r} uses {{{unknown[0]}}}, which is not a template field.",
                suggestion=f"Use only these fields: {names}.",
            )
        if "video_id" not in fields:
            raise InvalidOption(
                f"filename={text!r} does not contain {{video_id}}, so names could repeat.",
                suggestion='Add {video_id}, as in "{title} [{video_id}].{ext}".',
            )
        if any("{" in (spec or "") for _, field, spec, _ in parsed if field is not None):
            raise InvalidOption(f"filename={text!r} puts a field inside a format spec.")
        template = cls(text, fields)
        try:
            sample = template.render(_SAMPLE_FIELDS)
        except (ValueError, TypeError) as error:
            raise InvalidOption(f"filename={text!r} cannot be filled in: {error}.") from None
        if "/" in sample or "\\" in sample:
            raise InvalidOption(
                f"filename={text!r} makes a path; it must be a plain file name.",
                suggestion="Remove / and \\ from the template and choose the folder with out_dir.",
            )
        forbidden = _FORBIDDEN.search(sample)
        if forbidden is not None:
            raise InvalidOption(
                f"filename={text!r} contains {forbidden.group()!r}, which Windows does not allow "
                "in a file name.",
                suggestion=(
                    'Leave <>:"|?* and control characters out of the template; titles and '
                    "channels are made safe for you."
                ),
            )
        if sample.endswith((".", " ")):
            raise InvalidOption(
                f"filename={text!r} makes a name that ends with {sample[-1]!r}, which Windows "
                "does not allow.",
                suggestion='End the template with a field or a letter, as in "{video_id}.{ext}".',
            )
        return template

    def render(self, values: Mapping[str, str | int]) -> str:
        """The file name for ``values``; the title is shortened when the name would pass
        ``MAX_BULK_NAME_BYTES`` UTF-8 bytes."""
        safe = dict(values)
        for field, (chars, size) in _SAFE_FIELDS.items():
            if field in safe:
                safe[field] = safe_name(str(safe[field]), max_chars=chars, max_bytes=size)
        if "title" in safe and not safe["title"]:
            safe["title"] = str(values.get("video_id", ""))
        name = self.text.format(**safe)
        excess = len(name.encode("utf-8")) - MAX_BULK_NAME_BYTES
        title = str(safe.get("title", ""))
        if excess > 0 and title:
            budget = max(0, len(title.encode("utf-8")) - excess)
            safe["title"] = safe_name(title, max_bytes=budget)
            name = self.text.format(**safe)
        return name

    def pattern(
        self, values: Mapping[str, str | int], globs: Mapping[str, str] | None = None
    ) -> str:
        """A glob pattern that matches every name :meth:`render` can give when only ``values``
        are known: literal text and known values are escaped, a field in ``globs`` becomes that
        glob as it is, and any other field (``title`` and ``channel`` always) becomes ``*``."""
        formatter = Formatter()
        parts: list[str] = []
        for literal, field, spec, conversion in formatter.parse(self.text):
            parts.append(glob_literal(literal))
            if field is None:
                continue
            if globs is not None and field in globs:
                parts.append(globs[field])
            elif field in values and field not in ("title", "channel"):
                value = formatter.convert_field(values[field], conversion)
                parts.append(glob_literal(formatter.format_field(value, spec or "")))
            else:
                parts.append("*")
        return "".join(parts)


def glob_literal(text: str) -> str:
    """``text`` as a glob pattern that matches only itself (``[`` becomes ``[[]``)."""
    return _GLOB_MAGIC.sub(r"[\1]", text)


def part_name(target: PurePath, itag: int) -> PurePath:
    """Where stream ``itag`` of ``target`` is downloaded: ``rick.mp4`` gives ``rick.mp4.137.part``."""
    return target.with_name(f"{target.name}.{itag}.part")


_SAFE_FIELDS: dict[str, tuple[int, int]] = {
    "title": (MAX_NAME_CHARS, MAX_NAME_BYTES),
    "channel": (MAX_NAME_CHARS, MAX_NAME_BYTES),
    "language_code": (35, 35),
}


def _shorten(text: str, max_chars: int, max_bytes: int) -> str:
    text = text[:max_chars]
    while len(text.encode("utf-8")) > max_bytes:
        text = text[:-1]
    return text
