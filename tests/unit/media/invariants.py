"""Invariants every muxed file must satisfy, checked by re-parsing it with ``progressive``."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from fractions import Fraction
from itertools import pairwise

from utmax.core.media.boxes import U32_MAX, BoxHeader, ByteSource
from utmax.core.media.fmp4 import IndexedTrack, index_fragments
from utmax.core.media.mux import MuxPlan, PlanSource
from utmax.core.media.progressive import ProgressiveFile, Track, parse_progressive


def check_file(
    plan: MuxPlan, sources: Sequence[ByteSource], *, hash_payloads: bool = True
) -> ProgressiveFile:
    """Re-parse the planned file and compare every media track with its input track.

    Checks the ``ftyp``/``moov``/``mdat`` layout, a 64-bit ``mdat`` header exactly when the box
    needs it, ``co64`` exactly when a track's offsets need it, per-sample sizes, durations,
    composition offsets, sync flags and sample descriptions, per-sample payload hashes, chunk
    bounds (1 s of media, 10 s of subtitles) and that chunks are stored in time order.
    """
    output = PlanSource(plan, sources)
    parsed = parse_progressive(output)
    assert [header.kind for header in parsed.boxes] == ["ftyp", "moov", "mdat"]
    mdat = parsed.boxes[2]
    assert mdat.header_size == (16 if mdat.size > U32_MAX else 8)
    assert mdat.end == output.size == plan.size
    inputs = [
        (number, track)
        for number, source in enumerate(sources)
        for track in index_fragments(source)
    ]
    for (number, expected), track in zip(inputs, parsed.tracks, strict=False):
        _check_track(track, expected, output, sources[number], hash_payloads=hash_payloads)
    for track in parsed.tracks:
        _check_chunks(track, mdat)
    _check_time_order(parsed)
    assert parsed.duration == max(track.duration for track in parsed.tracks)
    assert parsed.next_track_id == len(parsed.tracks) + 1
    return parsed


def _check_track(
    track: Track,
    expected: IndexedTrack,
    output: ByteSource,
    source: ByteSource,
    *,
    hash_payloads: bool,
) -> None:
    samples, table = track.samples, expected.samples
    assert track.timescale == expected.header.timescale
    assert len(samples) == len(table)
    assert [sample.size for sample in samples] == list(table.sizes)
    assert [sample.duration for sample in samples] == list(table.durations)
    assert [sample.cto for sample in samples] == list(table.ctos)
    assert [sample.sync for sample in samples] == [bool(flag) for flag in table.sync]
    assert [sample.description for sample in samples] == list(table.descriptions)
    if hash_payloads:
        for sample, offset in zip(samples, table.offsets, strict=True):
            assert _digest(output, sample.offset, sample.size) == _digest(
                source, offset, sample.size
            )


def _check_chunks(track: Track, mdat: BoxHeader) -> None:
    span = track.timescale * (10 if track.handler == "sbtl" else 1)
    offsets = [chunk.offset for chunk in track.chunks]
    assert track.chunk_box == ("co64" if offsets and max(offsets) > U32_MAX else "stco")
    for chunk in track.chunks:
        first = track.samples[chunk.first_sample]
        last = track.samples[chunk.first_sample + chunk.count - 1]
        assert last.dts - first.dts < span
        assert mdat.payload_offset <= first.offset
        assert last.offset + last.size <= mdat.end


def _check_time_order(parsed: ProgressiveFile) -> None:
    starts: list[tuple[int, Fraction]] = []
    for track in parsed.tracks:
        lead = Fraction(0)
        if track.edits and track.edits[0].media_time == -1:
            lead = Fraction(track.edits[0].duration, 1000)
        for chunk in track.chunks:
            dts = track.samples[chunk.first_sample].dts
            starts.append((chunk.offset, lead + Fraction(dts, track.timescale)))
    times = [time for _, time in sorted(starts)]
    tolerance = Fraction(1, 1000)
    assert all(later >= earlier - tolerance for earlier, later in pairwise(times))


def _digest(source: ByteSource, offset: int, size: int) -> bytes:
    return hashlib.sha256(source.read(offset, size)).digest()
