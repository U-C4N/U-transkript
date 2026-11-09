"""Tests for the Matroska description of MP4 sample entries."""

from __future__ import annotations

import struct

import pytest

from tests.helpers.fmp4_factory import AV1C, AVCC, Sample, Track, simple_file
from utmax.core.media import ebml
from utmax.core.media.boxes import BytesSource, box, u16, u32
from utmax.core.media.codecs import audio_specific_config, colour_element, mp4_codec
from utmax.core.media.fmp4 import index_fragments
from utmax.errors import MuxError


def entry_of(track: Track) -> bytes:
    (indexed,) = index_fragments(BytesSource(simple_file([Sample(512, 100)], track=track)))
    return indexed.header.sample_entries[0]


def test_h264_av1_and_aac_get_their_matroska_codecs() -> None:
    avc = mp4_codec(entry_of(Track()))
    assert (avc.kind, avc.codec_id, avc.codec_private) == ("video", "V_MPEG4/ISO/AVC", AVCC)
    assert (avc.width, avc.height, avc.colour) == (640, 360, None)
    av1 = mp4_codec(entry_of(Track(codec="av01")))
    assert (av1.codec_id, av1.codec_private) == ("V_AV1", AV1C)
    aac = mp4_codec(entry_of(Track(handler="soun", codec="mp4a", timescale=44100)))
    assert (aac.kind, aac.codec_id, aac.sampling_frequency, aac.channels) == (
        "audio",
        "A_AAC",
        44100.0,
        2,
    )
    assert aac.codec_private == bytes.fromhex("1210") + bytes(14)


def es_descriptor(flags: int, extra: bytes, config: bytes, *, long_sizes: bool = False) -> bytes:
    specific = bytes([0x05]) + (b"\x80\x80\x80" if long_sizes else b"") + bytes([len(config)])
    decoder = bytes([0x04, 13 + len(specific) + len(config), 0x40, 0x15]) + bytes(11)
    body = b"\x00\x01" + bytes([flags]) + extra + decoder + specific + config
    return bytes(4) + bytes([0x03, len(body)]) + body


def test_optional_es_fields_and_long_descriptor_sizes_are_skipped() -> None:
    extra = b"\x00\x02" + b"\x03abc" + b"\x00\x03"  # depends-on ID, URL, OCR ID
    assert audio_specific_config(es_descriptor(0xE0, extra, b"\x11\x90")) == b"\x11\x90"
    assert audio_specific_config(es_descriptor(0, b"", b"\x12\x10", long_sizes=True)) == b"\x12\x10"


@pytest.mark.parametrize(
    ("esds", "message"),
    [
        (bytes(4), "truncated"),
        (bytes(4) + b"\x04\x00", "does not start with an ES descriptor"),
        (bytes(4) + b"\x03\x05\x00\x01\x00\x06\x00", "no decoder configuration"),
        (bytes(4) + b"\x03\x05\x00\x01\x00\x04\x0d" + bytes(13) + b"\x06\x00", "decoder-specific"),
        (
            bytes(4) + b"\x03\x05\x00\x01\x00\x04\x0d" + bytes(13) + b"\x05\x09ab",
            "decoder-specific",
        ),
    ],
)
def test_broken_esds_is_a_mux_error(esds: bytes, message: str) -> None:
    with pytest.raises(MuxError, match=message):
        audio_specific_config(esds)


def test_hdr_boxes_become_a_matroska_colour_element() -> None:
    boxes = {
        "colr": b"nclx" + struct.pack(">HHH", 9, 16, 9) + b"\x80",
        "clli": struct.pack(">HH", 1000, 400),
        "mdcv": struct.pack(
            ">8H2I", 8500, 39850, 6550, 2300, 35400, 14600, 15635, 16450, 10_000_000, 50
        ),
    }
    colour = colour_element(boxes)
    assert colour is not None
    ((element_id, payload),) = ebml.children(colour)
    fields = dict(ebml.children(payload))
    assert element_id == ebml.COLOUR
    assert {
        name: ebml.uint_value(fields[key])
        for name, key in (
            ("matrix", ebml.MATRIX_COEFFICIENTS),
            ("range", ebml.RANGE),
            ("transfer", ebml.TRANSFER_CHARACTERISTICS),
            ("primaries", ebml.PRIMARIES),
            ("max_cll", ebml.MAX_CLL),
            ("max_fall", ebml.MAX_FALL),
        )
    } == {"matrix": 9, "range": 2, "transfer": 16, "primaries": 9, "max_cll": 1000, "max_fall": 400}
    mastering = {
        key: ebml.float_value(value)
        for key, value in ebml.children(fields[ebml.MASTERING_METADATA])
    }
    assert mastering[ebml.PRIMARY_R_X] == pytest.approx(0.708)
    assert mastering[ebml.PRIMARY_G_X] == pytest.approx(0.17)
    assert mastering[ebml.PRIMARY_B_Y] == pytest.approx(0.046)
    assert mastering[ebml.WHITE_POINT_X] == pytest.approx(0.3127)
    assert (mastering[ebml.LUMINANCE_MAX], mastering[ebml.LUMINANCE_MIN]) == (1000.0, 0.005)


def test_quicktime_colours_have_no_range_and_nothing_gives_no_element() -> None:
    colour = colour_element({"colr": b"nclc" + struct.pack(">HHH", 1, 1, 1)})
    assert colour is not None
    assert ebml.RANGE not in dict(ebml.children(ebml.children(colour)[0][1]))
    assert colour_element({}) is None
    assert colour_element({"colr": b"prof" + bytes(20)}) is None


def test_other_codecs_and_entries_without_their_configuration_are_refused() -> None:
    with pytest.raises(MuxError, match="cannot go into Matroska"):
        mp4_codec(box("hev1", bytes(78)))
    with pytest.raises(MuxError, match="no 'avcC' box"):
        mp4_codec(box("avc1", bytes(78)))
    with pytest.raises(MuxError, match="no 'esds' box"):
        mp4_codec(box("mp4a", bytes(28)))
    with pytest.raises(MuxError, match="truncated"):
        mp4_codec(box("avc1", bytes(10)))


@pytest.mark.parametrize(
    ("config", "rate"),
    [
        (bytes.fromhex("1190"), 48000),  # AAC-LC, index 3
        (bytes.fromhex("f8e8"), 44100),  # escaped object type 39, then index 4
        (bytes.fromhex("17805dc000"), 48000),  # index 15, then an explicit 24-bit rate
        (b"\x12", 44100),  # too short to read
    ],
)
def test_the_aac_config_gives_the_rate_of_version_2_entries(config: bytes, rate: int) -> None:
    fields = bytes(6) + u16(1) + u16(2) + bytes(6) + u16(2) + bytes(6) + u32(0)
    esds = box("esds", bytes(4), es_descriptor(0, b"", config)[4:])
    entry = box("mp4a", fields, bytes(64 - 28), esds)
    assert mp4_codec(entry).sampling_frequency == rate
