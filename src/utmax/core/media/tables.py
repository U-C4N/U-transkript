"""Sample tables (``stbl`` children), chunking and edit lists for progressive MP4/MOV files.

Box layouts follow ISO/IEC 14496-12 (section 8.6 and 8.7); the writing conventions (run-length
``stts``/``ctts``/``stsc``, ``stss`` only when some samples are not sync samples, ``co64``
only when an offset needs it) match FFmpeg's ``libavformat/movenc.c``.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence

from utmax.core.media.boxes import I32_MAX, box, full_box, i32, i64, u32, u64
from utmax.core.media.fmp4 import Edit

__all__ = [
    "chunk_offsets_box",
    "chunk_ranges",
    "ctts_box",
    "edts_box",
    "run_lengths",
    "stsc_box",
    "stss_box",
    "stsz_box",
    "stts_box",
]


def run_lengths(values: Iterable[int]) -> list[tuple[int, int]]:
    """``(count, value)`` pairs for consecutive equal values: ``[5, 5, 7]`` -> ``[(2, 5), (1, 7)]``."""
    runs: list[tuple[int, int]] = []
    for value in values:
        if runs and runs[-1][1] == value:
            runs[-1] = (runs[-1][0] + 1, value)
        else:
            runs.append((1, value))
    return runs


def stts_box(durations: Sequence[int]) -> bytes:
    """Decoding time to sample: run-length encoded sample durations."""
    runs = run_lengths(durations)
    return full_box(
        "stts", 0, 0, u32(len(runs)), *(u32(count) + u32(value) for count, value in runs)
    )


def ctts_box(offsets: Sequence[int]) -> bytes | None:
    """Composition offsets, or ``None`` when every offset is zero.

    Version 1 (signed offsets) is used exactly when an offset is negative.
    """
    if not any(offsets):
        return None
    signed = min(offsets) < 0
    pack = i32 if signed else u32
    runs = run_lengths(offsets)
    return full_box(
        "ctts",
        1 if signed else 0,
        0,
        u32(len(runs)),
        *(u32(count) + pack(value) for count, value in runs),
    )


def stss_box(sync: bytes | bytearray) -> bytes | None:
    """1-based numbers of the sync samples, or ``None`` when every sample is a sync sample."""
    if all(sync):
        return None
    numbers = [index + 1 for index, flag in enumerate(sync) if flag]
    return full_box("stss", 0, 0, u32(len(numbers)), struct.pack(f">{len(numbers)}I", *numbers))


def stsz_box(sizes: Sequence[int]) -> bytes:
    """Sample sizes: one shared size when all are equal, else one entry per sample."""
    if sizes and all(size == sizes[0] for size in sizes):
        return full_box("stsz", 0, 0, u32(sizes[0]), u32(len(sizes)))
    return full_box("stsz", 0, 0, u32(0), u32(len(sizes)), struct.pack(f">{len(sizes)}I", *sizes))


def stsc_box(chunks: Sequence[tuple[int, int]]) -> bytes:
    """Sample to chunk from ``(samples in chunk, sample description index)`` per chunk."""
    entries: list[bytes] = []
    previous: tuple[int, int] | None = None
    for number, chunk in enumerate(chunks, start=1):
        if chunk != previous:
            entries.append(u32(number) + u32(chunk[0]) + u32(chunk[1]))
            previous = chunk
    return full_box("stsc", 0, 0, u32(len(entries)), *entries)


def chunk_offsets_box(offsets: Sequence[int], *, wide: bool) -> bytes:
    """``co64`` (64-bit offsets) when ``wide``, else ``stco``."""
    if wide:
        return full_box("co64", 0, 0, u32(len(offsets)), struct.pack(f">{len(offsets)}Q", *offsets))
    return full_box("stco", 0, 0, u32(len(offsets)), struct.pack(f">{len(offsets)}I", *offsets))


def chunk_ranges(
    dts: Sequence[int], descriptions: Sequence[int], *, span: int
) -> list[tuple[int, int]]:
    """Group samples into chunks as ``(first sample, count)`` pairs.

    A chunk ends before the first sample whose decode time is ``span`` ticks or more after the
    chunk's first sample, and wherever the sample description changes.
    """
    chunks: list[tuple[int, int]] = []
    first = 0
    for index in range(1, len(dts)):
        if dts[index] - dts[first] >= span or descriptions[index] != descriptions[first]:
            chunks.append((first, index - first))
            first = index
    if dts:
        chunks.append((first, len(dts) - first))
    return chunks


def edts_box(edits: Sequence[Edit]) -> bytes:
    """An ``edts`` box holding one ``elst``; version 1 (64-bit fields) only when needed."""
    wide = any(edit.duration >= I32_MAX or edit.media_time >= I32_MAX for edit in edits)
    entries = [_edit_entry(edit, wide=wide) for edit in edits]
    return box("edts", full_box("elst", 1 if wide else 0, 0, u32(len(entries)), *entries))


def _edit_entry(edit: Edit, *, wide: bool) -> bytes:
    if wide:
        return u64(edit.duration) + i64(edit.media_time) + u32(edit.rate)
    return u32(edit.duration) + i32(edit.media_time) + u32(edit.rate)
