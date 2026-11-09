"""Tests for EBML numbers, element IDs and values."""

from __future__ import annotations

import pytest

from utmax.core.media import ebml
from utmax.core.media.boxes import BytesSource
from utmax.errors import MuxError


@pytest.mark.parametrize(
    ("size", "encoded"),
    [
        (0, b"\x80"),
        (1, b"\x81"),
        (126, b"\xfe"),
        (127, b"\x40\x7f"),
        (16382, b"\x7f\xfe"),
        (16383, b"\x20\x3f\xff"),
    ],
)
def test_sizes_take_the_fewest_bytes_and_read_back(size: int, encoded: bytes) -> None:
    assert ebml.encode_size(size) == encoded
    assert ebml.read_vint(encoded, 0) == (size, len(encoded))


def test_fixed_width_sizes_and_their_limits() -> None:
    assert ebml.encode_size(5, length=8) == b"\x01" + bytes(6) + b"\x05"
    with pytest.raises(MuxError, match="does not fit 1 bytes"):
        ebml.encode_size(127, length=1)
    with pytest.raises(MuxError):
        ebml.encode_size(-1)
    with pytest.raises(MuxError):
        ebml.encode_size(1, length=9)


def test_a_size_of_all_ones_is_unknown() -> None:
    assert ebml.read_vint(b"\xff", 0) == (ebml.UNKNOWN_SIZE, 1)
    assert ebml.read_vint(b"\x01\xff\xff\xff\xff\xff\xff\xff", 0) == (ebml.UNKNOWN_SIZE, 8)


@pytest.mark.parametrize("data", [b"", b"\x00", b"\x40"])
def test_malformed_numbers_are_mux_errors(data: bytes) -> None:
    with pytest.raises(MuxError):
        ebml.read_vint(data, 0)


def test_ids_keep_their_marker_bits() -> None:
    assert ebml.encode_id(ebml.EBML) == b"\x1a\x45\xdf\xa3"
    assert ebml.encode_id(ebml.SIMPLE_BLOCK) == b"\xa3"
    assert ebml.read_id(b"\x1a\x45\xdf\xa3", 0) == (ebml.EBML, 4)
    for data in (b"", b"\x00", b"\x08\x00\x00\x00\x00", b"\x1a\x45"):
        with pytest.raises(MuxError, match="ID is malformed"):
            ebml.read_id(data, 0)


def test_values_and_children_round_trip() -> None:
    payload = (
        ebml.uint(ebml.TRACK_NUMBER, 2)
        + ebml.string(ebml.CODEC_ID, "V_VP9")
        + ebml.float64(ebml.SAMPLING_FREQUENCY, 48000.0)
        + ebml.uint(ebml.TRACK_UID, 7, width=8)
        + ebml.binary(ebml.CODEC_PRIVATE, b"\x01\x02")
        + ebml.uint(ebml.FLAG_LACING, 0)
    )
    (number, codec, rate, uid, private, lacing) = ebml.children(payload)
    assert ebml.uint_value(number[1]) == 2
    assert codec == (ebml.CODEC_ID, b"V_VP9")
    assert ebml.float_value(rate[1]) == 48000.0
    assert (len(uid[1]), ebml.uint_value(uid[1])) == (8, 7)
    assert private == (ebml.CODEC_PRIVATE, b"\x01\x02")
    assert lacing == (ebml.FLAG_LACING, b"\x00")


def test_floats_take_four_or_eight_bytes() -> None:
    assert ebml.float_value(bytes.fromhex("473b8000")) == 48000.0
    assert ebml.float_value(b"") == 0.0
    with pytest.raises(MuxError, match="only 4 or 8"):
        ebml.float_value(b"\x00\x00")


def test_children_must_fit_their_parent() -> None:
    with pytest.raises(MuxError, match="runs past"):
        ebml.children(ebml.encode_id(ebml.VOID) + b"\x85ab")
    with pytest.raises(MuxError, match="runs past"):
        ebml.children(ebml.encode_id(ebml.VOID) + b"\xff")


def test_headers_are_read_from_a_source() -> None:
    data = ebml.element(ebml.CLUSTER, b"x" * 300)
    header = ebml.read_header(BytesSource(data), 0)
    assert (header.element_id, header.header_size, header.size) == (ebml.CLUSTER, 6, 300)
    assert (header.payload_offset, header.end) == (6, 306)
