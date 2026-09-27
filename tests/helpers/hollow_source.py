"""Replay hollow media fixtures (recorded by scripts/make_media_fixtures.py) as byte sources."""

from __future__ import annotations

import json
import struct
from bisect import bisect_right
from functools import cache
from pathlib import Path
from typing import Any

MEDIA = Path(__file__).resolve().parent.parent / "fixtures" / "media"


class HollowSource:
    """A ByteSource over a hollow fixture: the real boxes, with zero-filled mdat payloads."""

    def __init__(self, data: bytes) -> None:
        self._starts: list[int] = []
        self._pieces: list[bytes | int] = []  # stored bytes, or the length of a run of zeros
        stored = virtual = 0
        while stored < len(data):
            size, kind = struct.unpack_from(">I4s", data, stored)
            header = 8
            if size == 1:
                (size,) = struct.unpack_from(">Q", data, stored + 8)
                header = 16
            kept = header if kind == b"mdat" else size
            self._starts.append(virtual)
            self._pieces.append(data[stored : stored + kept])
            if kind == b"mdat":
                self._starts.append(virtual + header)
                self._pieces.append(size - header)
            stored += kept
            virtual += size
        self.size = virtual

    @classmethod
    def load(cls, itag: int) -> HollowSource:
        """The recorded fixture of ``itag`` (137, 140 or 399)."""
        return cls((MEDIA / stream_facts(itag)["file"]).read_bytes())

    def read(self, offset: int, n: int) -> bytes:
        end = min(offset + n, self.size)
        out = bytearray()
        index = bisect_right(self._starts, offset) - 1
        while offset < end:
            piece, start = self._pieces[index], self._starts[index]
            length = piece if isinstance(piece, int) else len(piece)
            take = min(end, start + length) - offset
            if isinstance(piece, int):
                out += bytes(take)
            else:
                out += piece[offset - start : offset - start + take]
            offset += take
            index += 1
        return bytes(out)


@cache
def manifest() -> dict[str, Any]:
    """Facts about the recorded streams, read independently of utmax at recording time."""
    data: dict[str, Any] = json.loads((MEDIA / "manifest.json").read_text(encoding="utf-8"))
    return data


def stream_facts(itag: int) -> dict[str, Any]:
    """The manifest entry of one itag."""
    facts: dict[str, Any] = manifest()["streams"][str(itag)]
    return facts
