"""Tests for the box primitives."""

from __future__ import annotations

import pytest

from utmax.core.media.boxes import (
    BoxHeader,
    BytesSource,
    Reader,
    box,
    child_boxes,
    find_child,
    full_box,
    i16,
    i32,
    i64,
    iter_boxes,
    read_exact,
    require_child,
    u8,
    u16,
    u24,
    u32,
    u64,
)
from utmax.errors import MuxError


def test_integer_writers_are_big_endian() -> None:
    assert u8(0xAB) == b"\xab"
    assert u16(0x0102) == b"\x01\x02"
    assert u24(0x010203) == b"\x01\x02\x03"
    assert u32(0x01020304) == b"\x01\x02\x03\x04"
    assert u64(1) == b"\x00" * 7 + b"\x01"
    assert i16(-2) == b"\xff\xfe"
    assert i32(-1) == b"\xff\xff\xff\xff"
    assert i64(-1) == b"\xff" * 8


def test_box_and_full_box_layout() -> None:
    assert box("free") == b"\x00\x00\x00\x08free"
    assert box("abcd", b"xy", b"z") == b"\x00\x00\x00\x0babcdxyz"
    assert full_box("mfhd", 1, 0x020304, u32(7)) == (
        b"\x00\x00\x00\x10mfhd\x01\x02\x03\x04\x00\x00\x00\x07"
    )


def test_iter_boxes_reads_32_bit_64_bit_and_to_the_end_sizes() -> None:
    wide = u32(1) + b"mdat" + u64(20) + b"abcd"
    to_end = u32(0) + b"free" + b"rest"
    data = box("ftyp", b"isom") + wide + to_end
    headers = list(iter_boxes(BytesSource(data)))
    assert headers == [
        BoxHeader("ftyp", 0, 12, 8),
        BoxHeader("mdat", 12, 20, 16),
        BoxHeader("free", 32, 12, 8),
    ]
    assert headers[1].payload_offset == 28
    assert headers[1].payload_size == 4
    assert headers[1].end == 32


def test_iter_boxes_honours_start_and_end() -> None:
    data = box("aaaa") + box("bbbb") + box("cccc")
    assert [h.kind for h in iter_boxes(BytesSource(data), 8, 16)] == ["bbbb"]


@pytest.mark.parametrize(
    "data",
    [
        b"\x00\x00\x00",  # shorter than a header
        u32(1) + b"mdat" + b"\x00\x00",  # truncated 64-bit size
        u32(4) + b"free",  # smaller than its own header
        u32(64) + b"moov" + bytes(8),  # runs past the end
    ],
)
def test_iter_boxes_rejects_broken_headers(data: bytes) -> None:
    with pytest.raises(MuxError):
        list(iter_boxes(BytesSource(data)))


def test_child_boxes_and_lookups() -> None:
    payload = box("mvhd", b"1") + u32(1) + b"trak" + u64(17) + b"x" + u32(0) + b"udta" + b"yz"
    assert child_boxes(payload, context="moov") == [("mvhd", b"1"), ("trak", b"x"), ("udta", b"yz")]
    assert find_child(payload, "trak", context="moov") == b"x"
    assert find_child(payload, "mvex", context="moov") is None
    assert require_child(payload, "udta", context="moov") == b"yz"
    with pytest.raises(MuxError, match="'moov' box has no 'mvex'"):
        require_child(payload, "mvex", context="moov")


@pytest.mark.parametrize(
    "payload",
    [b"\x00\x00\x00\x09tra", u32(1) + b"trak" + b"\x00", u32(3) + b"trak", u32(99) + b"trak"],
)
def test_child_boxes_rejects_broken_children(payload: bytes) -> None:
    with pytest.raises(MuxError, match="'moov'"):
        child_boxes(payload, context="moov")


def test_reader_reads_every_width_and_stops_at_the_end() -> None:
    data = b"\x01" + b"\x00\x02" + b"\x00\x00\x03" + u32(4) + u64(5) + i16(-6) + i32(-7)
    data += i64(-8) + b"moov" + b"tail"
    reader = Reader(data, "test")
    values = [reader.u8(), reader.u16(), reader.u24(), reader.u32(), reader.u64()]
    values += [reader.i16(), reader.i32(), reader.i64()]
    assert values == [1, 2, 3, 4, 5, -6, -7, -8]
    assert reader.fourcc() == "moov"
    reader.skip(1)
    assert reader.remaining == 3
    assert reader.rest() == b"ail"
    with pytest.raises(MuxError, match="'test' box is truncated"):
        reader.u8()


def test_read_exact_reports_truncated_inputs() -> None:
    source = BytesSource(b"0123456789")
    assert read_exact(source, 2, 3) == b"234"
    assert read_exact(source, 10, 0) == b""
    with pytest.raises(MuxError, match="needed 4 bytes at offset 8, got 2"):
        read_exact(source, 8, 4)
