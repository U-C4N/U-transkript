"""ISO base media file format primitives: byte sources, box headers, readers and writers.

MP4, M4A and QuickTime files are trees of boxes: a 32-bit big-endian size, a four-character
type and a payload. Size 1 means a 64-bit size follows the type; size 0 means the box runs to
the end of the file. Every integer is big-endian.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from utmax.errors import MuxError

__all__ = [
    "I32_MAX",
    "U32_MAX",
    "BoxHeader",
    "ByteSource",
    "BytesSource",
    "Reader",
    "box",
    "child_boxes",
    "find_child",
    "full_box",
    "i16",
    "i32",
    "i64",
    "iter_boxes",
    "read_exact",
    "require_child",
    "u8",
    "u16",
    "u24",
    "u32",
    "u64",
]

U32_MAX = 0xFFFF_FFFF
I32_MAX = 0x7FFF_FFFF


class ByteSource(Protocol):
    """Random read access to one input file, such as a downloaded stream."""

    @property
    def size(self) -> int:
        """Total number of bytes."""
        ...

    def read(self, offset: int, n: int) -> bytes:
        """Up to ``n`` bytes starting at ``offset`` (fewer only at the end of the data)."""
        ...


@dataclass(frozen=True, slots=True)
class BytesSource:
    """A :class:`ByteSource` over bytes held in memory."""

    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)

    def read(self, offset: int, n: int) -> bytes:
        return self.data[offset : offset + n]


@dataclass(frozen=True, slots=True)
class BoxHeader:
    """Where one box sits in a file: its type, first byte, total size and header size."""

    kind: str
    offset: int
    size: int
    header_size: int

    @property
    def payload_offset(self) -> int:
        """The first byte after the header."""
        return self.offset + self.header_size

    @property
    def payload_size(self) -> int:
        """The number of bytes after the header."""
        return self.size - self.header_size

    @property
    def end(self) -> int:
        """The first byte after the box."""
        return self.offset + self.size


def read_exact(source: ByteSource, offset: int, n: int) -> bytes:
    """Exactly ``n`` bytes at ``offset``; a short read means the input is truncated."""
    data = source.read(offset, n) if n > 0 else b""
    if len(data) != n:
        raise MuxError(
            f"The input ends early: needed {n} bytes at offset {offset}, got {len(data)}."
        )
    return data


def iter_boxes(source: ByteSource, start: int = 0, end: int | None = None) -> Iterator[BoxHeader]:
    """The boxes laid end to end in ``source[start:end]`` (the top level by default)."""
    limit = source.size if end is None else end
    offset = start
    while offset < limit:
        if limit - offset < 8:
            raise MuxError(f"A box header at offset {offset} is truncated.")
        size, raw = struct.unpack(">I4s", read_exact(source, offset, 8))
        header_size = 8
        if size == 1:
            if limit - offset < 16:
                raise MuxError(f"A 64-bit box header at offset {offset} is truncated.")
            (size,) = struct.unpack(">Q", read_exact(source, offset + 8, 8))
            header_size = 16
        elif size == 0:
            size = limit - offset
        kind = raw.decode("latin-1")
        if size < header_size or offset + size > limit:
            raise MuxError(f"The {kind!r} box at offset {offset} has an impossible size ({size}).")
        yield BoxHeader(kind, offset, size, header_size)
        offset += size


def child_boxes(payload: bytes, *, context: str) -> list[tuple[str, bytes]]:
    """The boxes inside a container's ``payload`` as ``(type, payload)`` pairs, in order."""
    children: list[tuple[str, bytes]] = []
    offset = 0
    while offset < len(payload):
        if len(payload) - offset < 8:
            raise MuxError(f"A box inside {context!r} is truncated.")
        size, raw = struct.unpack_from(">I4s", payload, offset)
        header_size = 8
        if size == 1:
            if len(payload) - offset < 16:
                raise MuxError(f"A 64-bit box inside {context!r} is truncated.")
            (size,) = struct.unpack_from(">Q", payload, offset + 8)
            header_size = 16
        elif size == 0:
            size = len(payload) - offset
        kind = raw.decode("latin-1")
        if size < header_size or offset + size > len(payload):
            raise MuxError(f"The {kind!r} box inside {context!r} has an impossible size ({size}).")
        children.append((kind, payload[offset + header_size : offset + size]))
        offset += size
    return children


def find_child(payload: bytes, kind: str, *, context: str) -> bytes | None:
    """The payload of the first ``kind`` box inside ``payload``, or ``None``."""
    return next(
        (body for name, body in child_boxes(payload, context=context) if name == kind), None
    )


def require_child(payload: bytes, kind: str, *, context: str) -> bytes:
    """Like :func:`find_child`, but a missing box is an error."""
    body = find_child(payload, kind, context=context)
    if body is None:
        raise MuxError(f"The {context!r} box has no {kind!r} box inside.")
    return body


class Reader:
    """A big-endian cursor over a box payload; reading past the end raises :class:`MuxError`."""

    def __init__(self, data: bytes, context: str) -> None:
        self._data = data
        self._offset = 0
        self._context = context

    @property
    def remaining(self) -> int:
        """Bytes left to read."""
        return len(self._data) - self._offset

    def take(self, n: int) -> bytes:
        """The next ``n`` bytes."""
        if n < 0 or n > self.remaining:
            raise MuxError(f"The {self._context!r} box is truncated.")
        chunk = self._data[self._offset : self._offset + n]
        self._offset += n
        return chunk

    def skip(self, n: int) -> None:
        """Skip ``n`` bytes."""
        self.take(n)

    def rest(self) -> bytes:
        """Everything that has not been read yet."""
        return self.take(self.remaining)

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int.from_bytes(self.take(2), "big")

    def u24(self) -> int:
        return int.from_bytes(self.take(3), "big")

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "big")

    def u64(self) -> int:
        return int.from_bytes(self.take(8), "big")

    def i16(self) -> int:
        return int.from_bytes(self.take(2), "big", signed=True)

    def i32(self) -> int:
        return int.from_bytes(self.take(4), "big", signed=True)

    def i64(self) -> int:
        return int.from_bytes(self.take(8), "big", signed=True)

    def fourcc(self) -> str:
        return self.take(4).decode("latin-1")


def u8(value: int) -> bytes:
    return struct.pack(">B", value)


def u16(value: int) -> bytes:
    return struct.pack(">H", value)


def u24(value: int) -> bytes:
    return value.to_bytes(3, "big")


def u32(value: int) -> bytes:
    return struct.pack(">I", value)


def u64(value: int) -> bytes:
    return struct.pack(">Q", value)


def i16(value: int) -> bytes:
    return struct.pack(">h", value)


def i32(value: int) -> bytes:
    return struct.pack(">i", value)


def i64(value: int) -> bytes:
    return struct.pack(">q", value)


def box(kind: str, *parts: bytes) -> bytes:
    """A box with a 32-bit size header around the concatenated ``parts``."""
    payload = b"".join(parts)
    return struct.pack(">I4s", len(payload) + 8, kind.encode("latin-1")) + payload


def full_box(kind: str, version: int, flags: int, *parts: bytes) -> bytes:
    """A "full box": a box whose payload starts with a version byte and 24 bits of flags."""
    return box(kind, u8(version), u24(flags), *parts)
