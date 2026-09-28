"""Tests for sample tables, chunking and edit lists."""

from __future__ import annotations

from utmax.core.media.boxes import box, full_box, i32, i64, u32, u64
from utmax.core.media.fmp4 import Edit
from utmax.core.media.tables import (
    chunk_offsets_box,
    chunk_ranges,
    ctts_box,
    edts_box,
    run_lengths,
    stsc_box,
    stss_box,
    stsz_box,
    stts_box,
)


def test_run_lengths() -> None:
    assert run_lengths([]) == []
    assert run_lengths([5, 5, 7, 5]) == [(2, 5), (1, 7), (1, 5)]


def test_stts_is_run_length_encoded() -> None:
    assert stts_box([512, 512, 512, 1024]) == full_box(
        "stts", 0, 0, u32(2), u32(3), u32(512), u32(1), u32(1024)
    )


def test_ctts_is_omitted_unsigned_or_signed_as_needed() -> None:
    assert ctts_box([0, 0, 0]) is None
    assert ctts_box([512, 512, 0]) == full_box(
        "ctts", 0, 0, u32(2), u32(2), u32(512), u32(1), u32(0)
    )
    assert ctts_box([1024, -512]) == full_box(
        "ctts", 1, 0, u32(2), u32(1), i32(1024), u32(1), i32(-512)
    )


def test_stss_lists_sync_samples_only_when_some_are_not() -> None:
    assert stss_box(bytearray([1, 1, 1])) is None
    assert stss_box(bytearray([1, 0, 0, 1])) == full_box("stss", 0, 0, u32(2), u32(1), u32(4))


def test_stsz_shares_one_size_when_all_are_equal() -> None:
    assert stsz_box([6, 6, 6]) == full_box("stsz", 0, 0, u32(6), u32(3))
    assert stsz_box([6, 7]) == full_box("stsz", 0, 0, u32(0), u32(2), u32(6), u32(7))
    assert stsz_box([]) == full_box("stsz", 0, 0, u32(0), u32(0))


def test_stsc_starts_an_entry_whenever_count_or_description_changes() -> None:
    chunks = [(10, 1), (10, 1), (4, 1), (4, 2), (4, 2)]
    assert stsc_box(chunks) == full_box(
        "stsc",
        0,
        0,
        u32(3),
        u32(1) + u32(10) + u32(1),
        u32(3) + u32(4) + u32(1),
        u32(4) + u32(4) + u32(2),
    )


def test_chunk_offsets_use_co64_only_when_asked() -> None:
    assert chunk_offsets_box([48, 1000], wide=False) == full_box(
        "stco", 0, 0, u32(2), u32(48), u32(1000)
    )
    assert chunk_offsets_box([48, 2**32], wide=True) == full_box(
        "co64", 0, 0, u32(2), u64(48), u64(2**32)
    )


def test_chunks_span_less_than_the_limit_and_split_on_new_descriptions() -> None:
    dts = [0, 400, 800, 1200, 1600, 2000, 2400]
    assert chunk_ranges(dts, [1] * 7, span=1000) == [(0, 3), (3, 3), (6, 1)]
    assert chunk_ranges(dts, [1, 1, 2, 2, 2, 2, 2], span=1000) == [(0, 2), (2, 3), (5, 2)]
    assert chunk_ranges([], [], span=1000) == []


def test_edit_lists_use_64_bit_fields_only_when_needed() -> None:
    entries = [u32(500) + i32(-1) + u32(0x10000), u32(1000) + i32(512) + u32(0x10000)]
    assert edts_box([Edit(500, -1), Edit(1000, 512)]) == box(
        "edts", full_box("elst", 0, 0, u32(2), *entries)
    )
    wide = u64(2**31) + i64(5) + u32(0x8000)
    assert edts_box([Edit(2**31, 5, 0x8000)]) == box("edts", full_box("elst", 1, 0, u32(1), wide))
