"""Tests for the ftyp and moov builders and their MP4/MOV/M4A differences."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.helpers.fmp4_factory import ESDS, Track, sample_entry
from utmax.core.media.boxes import Reader, box, child_boxes, find_child, full_box, u16, u32
from utmax.core.media.fmp4 import Edit
from utmax.core.media.moov import (
    UNITY_MATRIX,
    Flavor,
    TrackPlan,
    ftyp_box,
    moov_box,
    pack_language,
    quicktime_sound_entry,
    unpack_language,
)
from utmax.core.media.tx3g import sample_entry as tx3g_entry
from utmax.errors import MuxError

VIDEO = TrackPlan(
    track_id=1,
    kind="video",
    timescale=12800,
    language="und",
    tag=None,
    name=None,
    enabled=True,
    matrix=UNITY_MATRIX,
    width=640 << 16,
    height=360 << 16,
    edits=(Edit(2000, 512),),
    duration=2000,
    media_duration=25600,
    sample_entries=(sample_entry(Track()),),
    durations=[512] * 50,
    ctos=[512] * 50,
    sync=bytes([1] + [0] * 49),
    sizes=[100] * 50,
    chunks=((25, 1), (25, 1)),
)
AUDIO = replace(
    VIDEO,
    track_id=2,
    kind="audio",
    timescale=44100,
    language="eng",
    matrix=UNITY_MATRIX,
    width=0,
    height=0,
    edits=(),
    duration=1998,
    media_duration=88064,
    sample_entries=(sample_entry(Track(handler="soun", codec="mp4a")),),
    durations=[1024] * 86,
    ctos=[0] * 86,
    sync=bytes([1] * 86),
    sizes=[300] * 86,
    chunks=((43, 1), (43, 1)),
)
SUBTITLE = replace(
    AUDIO,
    track_id=3,
    kind="subtitle",
    timescale=1000,
    language="tur",
    tag="tr",
    name="Turkish (AI: claude=claude-opus-5)",
    enabled=False,
    duration=1500,
    media_duration=1500,
    sample_entries=(tx3g_entry(),),
    durations=[500, 1000],
    ctos=[0, 0],
    sync=bytes([1, 1]),
    sizes=[2, 9],
    chunks=((2, 1),),
)
TRACKS = (VIDEO, AUDIO, SUBTITLE)


def moov_children(
    flavor: Flavor, tracks: tuple[TrackPlan, ...] = TRACKS
) -> list[tuple[str, bytes]]:
    offsets = [[1000 * (n + 1)] * len(track.chunks) for n, track in enumerate(tracks)]
    moov = moov_box(flavor, tracks, offsets, [False] * len(tracks))
    assert moov[4:8] == b"moov"
    return child_boxes(moov[8:], context="moov")


def trak(flavor: Flavor, number: int) -> bytes:
    traks = [body for kind, body in moov_children(flavor) if kind == "trak"]
    return traks[number]


def path(payload: bytes, *kinds: str) -> bytes:
    for kind in kinds:
        found = find_child(payload, kind, context=kind)
        assert found is not None, kind
        payload = found
    return payload


@pytest.mark.parametrize(
    ("flavor", "codecs", "expected"),
    [
        ("mp4", {"avc1", "mp4a"}, b"isom" + u32(0x200) + b"isomiso2avc1mp41"),
        ("mp4", {"av01", "mp4a"}, b"isom" + u32(0x200) + b"isomiso2av01mp41"),
        ("mp4", {"mp4a"}, b"isom" + u32(0x200) + b"isomiso2mp41"),
        ("mov", {"avc1", "mp4a"}, b"qt  " + u32(0x200) + b"qt  "),
        ("m4a", {"mp4a"}, b"M4A " + u32(0x200) + b"M4A isomiso2mp41"),
    ],
)
def test_ftyp_brands(flavor: Flavor, codecs: set[str], expected: bytes) -> None:
    assert ftyp_box(flavor, codecs) == box("ftyp", expected)


def test_languages_pack_into_15_bits() -> None:
    assert pack_language("und") == 0x55C4
    assert pack_language("eng") == 0x15C7
    assert pack_language("tur") == 0x52B2
    assert pack_language("EN") == 0x55C4
    assert pack_language("t1r") == 0x55C4
    assert unpack_language(0x52B2) == "tur"
    assert unpack_language(17) == "und"  # a QuickTime language code, not ISO


def test_movie_header() -> None:
    mvhd = Reader(dict(moov_children("mp4"))["mvhd"], "mvhd")
    assert (mvhd.u8(), mvhd.u24()) == (0, 0)
    mvhd.skip(8)
    assert (mvhd.u32(), mvhd.u32()) == (1000, 2000)  # timescale, longest track
    mvhd.skip(4 + 2 + 10 + 36 + 24)
    assert mvhd.u32() == 4  # next track ID


def tkhd_fields(payload: bytes) -> tuple[int, int, int, int, int, int]:
    reader = Reader(path(payload, "tkhd"), "tkhd")
    reader.skip(1)
    flags = reader.u24()
    reader.skip(8)
    track_id = reader.u32()
    reader.skip(4)
    duration = reader.u32()
    reader.skip(10)
    group, volume = reader.u16(), reader.u16()
    reader.skip(38)
    return track_id, flags, duration, group, volume, reader.u32()


def test_track_headers_follow_ffmpeg() -> None:
    assert tkhd_fields(trak("mp4", 0)) == (1, 3, 2000, 0, 0, 640 << 16)
    assert tkhd_fields(trak("mp4", 1)) == (2, 3, 1998, 1, 0x100, 0)
    assert tkhd_fields(trak("mp4", 2)) == (3, 2, 1500, 3, 0, 0)  # disabled subtitle


@pytest.mark.parametrize(
    ("number", "handler", "name"),
    [
        (0, b"vide", b"VideoHandler"),
        (1, b"soun", b"SoundHandler"),
        (2, b"sbtl", b"Turkish (AI: claude=claude-opus-5)"),
    ],
)
def test_handler_names_are_c_strings_in_mp4_and_pascal_strings_in_mov(
    number: int, handler: bytes, name: bytes
) -> None:
    mp4 = path(trak("mp4", number), "mdia", "hdlr")
    assert mp4 == bytes(8) + handler + bytes(12) + name + b"\x00"
    mov = path(trak("mov", number), "mdia", "hdlr")
    assert mov == bytes(4) + b"mhlr" + handler + bytes(12) + bytes([len(name)]) + name


def test_mov_media_information_has_a_data_handler() -> None:
    mp4_kinds = [
        kind for kind, _ in child_boxes(path(trak("mp4", 0), "mdia", "minf"), context="minf")
    ]
    mov_minf = path(trak("mov", 0), "mdia", "minf")
    mov_kinds = [kind for kind, _ in child_boxes(mov_minf, context="minf")]
    assert mp4_kinds == ["vmhd", "dinf", "stbl"]
    assert mov_kinds == ["vmhd", "hdlr", "dinf", "stbl"]
    data_handler = path(mov_minf, "hdlr")
    assert data_handler == bytes(4) + b"dhlrurl " + bytes(12) + b"\x0bDataHandler"


@pytest.mark.parametrize(("number", "header"), [(0, "vmhd"), (1, "smhd"), (2, "nmhd")])
def test_media_headers(number: int, header: str) -> None:
    minf = path(trak("mp4", number), "mdia", "minf")
    assert child_boxes(minf, context="minf")[0][0] == header


def mdhd_language(payload: bytes) -> int:
    mdhd = path(payload, "mdia", "mdhd")
    return int.from_bytes(mdhd[20:22], "big")


def test_languages_are_iso_in_mp4_and_quicktime_codes_in_mov_when_mapped() -> None:
    assert mdhd_language(trak("mp4", 2)) == pack_language("tur")
    assert mdhd_language(trak("mov", 2)) == 17  # QuickTime code for Turkish
    assert mdhd_language(trak("mov", 1)) == 0  # "eng" -> English
    assert mdhd_language(trak("mov", 0)) == pack_language("und")
    filipino = replace(SUBTITLE, language="fil", tag="fil")
    traks = [body for kind, body in moov_children("mov", (VIDEO, filipino)) if kind == "trak"]
    assert mdhd_language(traks[1]) == pack_language("fil")


def test_subtitle_tracks_carry_elng_and_a_name() -> None:
    subtitle = trak("mp4", 2)
    assert path(subtitle, "mdia", "elng") == bytes(4) + b"tr\x00"
    assert path(subtitle, "udta", "name") == b"Turkish (AI: claude=claude-opus-5)"
    assert find_child(trak("mp4", 0), "udta", context="trak") is None
    assert find_child(path(trak("mp4", 0), "mdia"), "elng", context="mdia") is None


def test_sample_tables() -> None:
    video = [
        kind
        for kind, _ in child_boxes(path(trak("mp4", 0), "mdia", "minf", "stbl"), context="stbl")
    ]
    audio = [
        kind
        for kind, _ in child_boxes(path(trak("mp4", 1), "mdia", "minf", "stbl"), context="stbl")
    ]
    assert video == ["stsd", "stts", "stss", "ctts", "stsc", "stsz", "stco"]
    assert audio == ["stsd", "stts", "stsc", "stsz", "stco"]
    stsd = path(trak("mp4", 1), "mdia", "minf", "stbl", "stsd")
    assert stsd == bytes(4) + u32(1) + sample_entry(Track(handler="soun", codec="mp4a"))


def test_wide_tracks_use_co64() -> None:
    moov = moov_box("mp4", (VIDEO,), [[2**32, 2**32 + 5000]], [True])
    stbl = path(child_boxes(moov[8:], context="moov")[1][1], "mdia", "minf", "stbl")
    assert find_child(stbl, "stco", context="stbl") is None
    assert path(stbl, "co64")[4:] == u32(2) + (2**32).to_bytes(8, "big") + (2**32 + 5000).to_bytes(
        8, "big"
    )


def test_edit_lists_are_written_only_when_present() -> None:
    assert find_child(trak("mp4", 0), "edts", context="trak") is not None
    assert find_child(trak("mp4", 1), "edts", context="trak") is None


def test_long_tracks_use_version_1_headers_in_mp4_and_fail_in_mov() -> None:
    long = replace(AUDIO, duration=2**31, media_duration=2**33, edits=())
    children = moov_children("mp4", (long,))
    assert dict(children)["mvhd"][0] == 1
    traks = [body for kind, body in children if kind == "trak"]
    assert path(traks[0], "tkhd")[0] == 1
    assert path(traks[0], "mdia", "mdhd")[0] == 1
    with pytest.raises(MuxError, match="too long for a QuickTime"):
        moov_children("mov", (long,))


def test_quicktime_sound_description_version_1_with_a_wave_box() -> None:
    entry = quicktime_sound_entry(
        sample_entry(Track(handler="soun", codec="mp4a")), samples_per_packet=1024
    )
    assert entry[4:8] == b"mp4a"
    # reference, version, revision, vendor, channels, bits, compression ID, packet size, rate...
    reader = Reader(entry, "mp4a")
    reader.skip(8 + 6)
    assert [reader.u16(), reader.u16(), reader.u16(), reader.u32()] == [1, 1, 0, 0]
    assert [reader.u16(), reader.u16(), reader.i16(), reader.u16()] == [2, 16, -2, 0]
    assert reader.u32() == 44100 << 16
    assert [reader.u32() for _ in range(4)] == [1024, 0, 0, 2]
    ((kind, wave),) = child_boxes(reader.rest(), context="mp4a")
    assert kind == "wave"
    assert child_boxes(wave, context="wave") == [
        ("frma", b"mp4a"),
        ("mp4a", bytes(4)),
        ("esds", ESDS),
        ("\x00\x00\x00\x00", b""),
    ]


def test_quicktime_sound_description_accepts_version_1_inputs() -> None:
    entry = box(
        "mp4a",
        bytes(6),
        u16(1),
        u16(1),
        bytes(6),
        u16(1),
        u16(16),
        u32(0),
        u32(48000 << 16),
        bytes(16),
        box("esds", ESDS),
    )
    converted = quicktime_sound_entry(entry, samples_per_packet=1024)
    assert Reader(converted, "mp4a").take(26)[24:26] == u16(1)  # mono kept


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (sample_entry(Track(handler="soun", codec="mp4a", channels=6)), "mono or stereo"),
        (sample_entry(Track(handler="soun", codec="mp4a", sample_rate=0)), "mono or stereo"),
        (
            sample_entry(
                Track(
                    handler="soun", codec="mp4a", extra_audio_box=full_box("srat", 0, 0, u32(96000))
                )
            ),
            "mono or stereo",
        ),
        (
            box("mp4a", bytes(6), u16(1), bytes(8), u16(2), u16(16), u32(0), u32(44100 << 16)),
            "no 'esds'",
        ),
        (box("mp4a", bytes(6), u16(1), u16(2), bytes(18)), "unsupported sample description"),
    ],
)
def test_audio_quicktime_cannot_describe_is_refused(entry: bytes, message: str) -> None:
    with pytest.raises(MuxError, match=message):
        quicktime_sound_entry(entry, samples_per_packet=1024)
