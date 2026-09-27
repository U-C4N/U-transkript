"""The synthetic fragment factory must itself be trustworthy: layout, payloads and guards."""

from __future__ import annotations

import pytest

from tests.helpers.fmp4_factory import (
    Run,
    Sample,
    Track,
    Traf,
    fragmented_file,
    init_segment,
    payload,
    sample_entry,
    simple_file,
    virtual_file,
)
from utmax.core.media.boxes import BytesSource, box, child_boxes, find_child, iter_boxes

VIDEO = Track()
AUDIO = Track(track_id=2, handler="soun", codec="mp4a", timescale=44100)


def two_track_fragments() -> list[list[Traf]]:
    video = (Sample(512, 700), Sample(512, 300, sync=False, cto=512))
    audio = (Sample(1024, 20), Sample(1024, 21), Sample(1024, 22))
    return [
        [Traf(1, (Run(video),)), Traf(2, (Run(audio),))],
        [Traf(1, (Run(video),), tfdt=1024), Traf(2, (Run(audio),), tfdt=3072)],
    ]


def test_layout_is_ftyp_moov_then_moof_mdat_pairs() -> None:
    data = fragmented_file([VIDEO, AUDIO], two_track_fragments(), after_moov=box("sidx"))
    kinds = [header.kind for header in iter_boxes(BytesSource(data))]
    assert kinds == ["ftyp", "moov", "sidx", "moof", "mdat", "moof", "mdat"]


def test_mdat_holds_each_run_in_order_with_unique_patterns() -> None:
    data = fragmented_file([VIDEO], [[Traf(1, (Run((Sample(512, 10), Sample(512, 7))),))]])
    mdat = next(h for h in iter_boxes(BytesSource(data)) if h.kind == "mdat")
    assert data[mdat.payload_offset : mdat.end] == payload(1, 0, 10) + payload(1, 1, 7)


def test_payload_patterns_differ_per_track_and_sample() -> None:
    assert len(payload(1, 0, 13)) == 13
    assert payload(1, 0, 16)[:8] == payload(1, 0, 16)[8:]
    assert len({payload(1, 0, 16), payload(1, 1, 16), payload(2, 0, 16)}) == 3


def test_virtual_file_reads_exactly_like_the_materialized_file() -> None:
    fragments = two_track_fragments()
    data = fragmented_file([VIDEO, AUDIO], fragments)
    virtual = virtual_file([VIDEO, AUDIO], fragments)
    assert virtual.size == len(data)
    assert virtual.read(0, virtual.size) == data
    for offset, length in ((0, 3), (5, 1000), (len(data) - 50, 49), (900, 1234)):
        assert virtual.read(offset, length) == data[offset : offset + length]
    assert virtual.read(len(data), 10) == b""


def test_init_segment_options() -> None:
    moov = child_boxes(init_segment([VIDEO], fragmented=False), context="file")[1][1]
    assert find_child(moov, "mvex", context="moov") is None
    wide = child_boxes(init_segment([VIDEO], header_version=1), context="file")[1][1]
    mvhd = find_child(wide, "mvhd", context="moov")
    assert mvhd is not None
    assert mvhd[0] == 1
    assert b"stsz" in init_segment([VIDEO], samples_in_moov=True)


@pytest.mark.parametrize(
    ("track", "marker"),
    [
        (VIDEO, b"avcC"),
        (Track(codec="av01"), b"av1C"),
        (AUDIO, b"esds"),
        (Track(codec="hvc1"), b"hvc1"),
    ],
)
def test_sample_entries(track: Track, marker: bytes) -> None:
    entry = sample_entry(track)
    assert entry[4:8] == track.codec.encode()
    assert marker in entry


def test_simple_file_splits_samples_into_fragments() -> None:
    data = simple_file([Sample(512, 5)] * 25, per_fragment=10)
    assert [h.kind for h in iter_boxes(BytesSource(data))].count("moof") == 3


@pytest.mark.parametrize(
    ("run", "traf_flags", "message"),
    [
        (Run((Sample(512, 5),), flags=0x000201), 0x020000, "omitted duration"),
        (Run((Sample(0, 5),), flags=0x000101), 0x020000, "omitted size"),
        (Run((Sample(0, 0, sync=False),), flags=0x000001), 0x020000, "omitted sample flags"),
        (Run((Sample(0, 0, cto=5),), flags=0x000001), 0x020000, "omitted composition"),
        (Run((Sample(0, 0),), flags=0x000000), 0x020000, "must start where"),
    ],
)
def test_impossible_specs_are_refused(run: Run, traf_flags: int, message: str) -> None:
    with pytest.raises(AssertionError, match=message):
        fragmented_file([VIDEO], [[Traf(1, (run,), flags=traf_flags)]])
