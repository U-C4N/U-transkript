"""Plan a progressive MP4, MOV or M4A file from fragmented streams.

:func:`plan_mux` never reads sample data. It indexes the inputs and lays out ``ftyp``, a
"faststart" ``moov`` and one ``mdat`` as a :class:`MuxPlan`: literal bytes (:class:`Blob`) and
byte ranges to copy from the inputs (:class:`CopyOp`), which
``utmax.adapters.files.write_mux_plan`` streams to disk. Chunks hold at most one second of
media and are interleaved by time; tracks keep their source timescales and edit lists
(converted to the 1000 Hz movie timescale); equal inputs give equal bytes. Outputs must stay
below 4 GiB for now.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import accumulate

from utmax.core.media.boxes import U32_MAX, ByteSource, read_exact, u32
from utmax.core.media.fmp4 import Edit, IndexedTrack, index_fragments
from utmax.core.media.moov import (
    MOVIE_TIMESCALE,
    Flavor,
    TrackKind,
    TrackPlan,
    ftyp_box,
    moov_box,
    quicktime_sound_entry,
    unpack_language,
)
from utmax.core.media.tables import chunk_ranges
from utmax.errors import MuxError

__all__ = [
    "FLAVORS",
    "Blob",
    "CopyOp",
    "Flavor",
    "MuxPlan",
    "PlanSource",
    "convert_edits",
    "plan_mux",
]

FLAVORS: tuple[Flavor, ...] = ("mp4", "mov", "m4a")
_MEDIA_CHUNK_SECONDS = 1
_KINDS: dict[tuple[str, str], TrackKind] = {
    ("vide", "avc1"): "video",
    ("vide", "av01"): "video",
    ("soun", "mp4a"): "audio",
}


@dataclass(frozen=True, slots=True)
class CopyOp:
    """Copy ``size`` bytes starting at ``offset`` of input number ``source``."""

    source: int
    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class Blob:
    """Bytes the muxer produced itself (headers, subtitle samples)."""

    data: bytes


@dataclass(frozen=True, slots=True)
class MuxPlan:
    """The output file as an ordered list of operations."""

    ops: tuple[CopyOp | Blob, ...]

    @property
    def size(self) -> int:
        """The size of the output file in bytes."""
        return sum(_op_size(op) for op in self.ops)


class PlanSource:
    """The bytes a :class:`MuxPlan` describes, readable without writing the file."""

    def __init__(self, plan: MuxPlan, sources: Sequence[ByteSource]) -> None:
        self._ops = plan.ops
        self._sources = sources
        self._starts = list(accumulate((_op_size(op) for op in plan.ops), initial=0))
        self.size = self._starts[-1]

    def read(self, offset: int, n: int) -> bytes:
        end = min(offset + n, self.size)
        parts: list[bytes] = []
        index = bisect_right(self._starts, offset) - 1
        while offset < end:
            op, start = self._ops[index], self._starts[index]
            take = min(end, self._starts[index + 1]) - offset
            if isinstance(op, Blob):
                parts.append(op.data[offset - start : offset - start + take])
            else:
                parts.append(read_exact(self._sources[op.source], op.offset + offset - start, take))
            offset += take
            index += 1
        return b"".join(parts)


@dataclass(frozen=True, slots=True)
class _Layout:
    """Where one track's chunks come from: byte ranges of one input."""

    chunks: list[tuple[int, int]]  # (first sample, sample count)
    times: list[Fraction]  # when each chunk starts, in seconds on the movie timeline
    source: int  # input number (media tracks)
    offsets: Sequence[int]  # sample offsets in that input
    sizes: Sequence[int]


def plan_mux(sources: Sequence[ByteSource], *, flavor: Flavor) -> MuxPlan:
    """Plan one progressive file from fragmented MP4 ``sources``.

    Every track of every source is kept in order (YouTube serves one track per stream).

    Raises:
        MuxError: an input is not fragmented MP4, is truncated, uses a codec other than H.264
            (avc1), AV1 (av01) or AAC (mp4a), or does not fit the flavor: video in m4a; AV1,
            multichannel audio or 64-bit durations in mov.
    """
    if flavor not in FLAVORS:
        raise MuxError(f"Unknown container flavor {flavor!r}; use mp4, mov or m4a.")
    if not sources:
        raise MuxError("There is nothing to mux: no input streams were given.")
    inputs = [
        (number, track)
        for number, source in enumerate(sources)
        for track in index_fragments(source)
    ]
    starts = [Fraction(track.samples.dts[0], track.header.timescale) for _, track in inputs]
    origin = min(starts)
    plans: list[TrackPlan] = []
    layouts: list[_Layout] = []
    seen: set[TrackKind] = set()
    for (number, track), start in zip(inputs, starts, strict=True):
        kind = _track_kind(flavor, track)
        plan, layout = _media_track(
            flavor,
            number,
            track,
            track_id=len(plans) + 1,
            kind=kind,
            lead=start - origin,
            enabled=kind not in seen,
        )
        seen.add(kind)
        plans.append(plan)
        layouts.append(layout)
    return _layout(flavor, plans, layouts)


def convert_edits(
    edits: Sequence[Edit],
    *,
    movie_timescale: int,
    timescale: int,
    first_dts: int,
    presentation_end: int,
    lead: Fraction,
) -> tuple[Edit, ...]:
    """A track's edit list on the output timeline (movie timescale 1000).

    Durations become milliseconds, rounded up and cut to the media that exists; media times
    move with the track's first decode time (the output track starts at 0); a positive
    ``lead`` (seconds after the earliest track starts) becomes a leading empty edit, rounded
    down like FFmpeg's.
    """
    converted: list[Edit] = []
    if lead > 0:
        converted.append(Edit(math.floor(lead * MOVIE_TIMESCALE), -1))
    for edit in edits:
        if edit.media_time < 0:
            converted.append(Edit(_to_movie(edit.duration, movie_timescale), -1, edit.rate))
            continue
        media_time = max(edit.media_time - first_dts, 0)
        available = presentation_end - media_time
        if available <= 0:
            continue
        duration = _to_movie(available, timescale)
        if edit.duration:
            duration = min(duration, _to_movie(edit.duration, movie_timescale))
        converted.append(Edit(duration, media_time, edit.rate))
    if lead > 0 and not edits:
        converted.append(Edit(_to_movie(presentation_end, timescale), 0))
    return tuple(converted)


def _track_kind(flavor: Flavor, track: IndexedTrack) -> TrackKind:
    header = track.header
    codecs = {entry[4:8].decode("latin-1") for entry in header.sample_entries}
    kind = _KINDS.get((header.handler, next(iter(codecs)))) if len(codecs) == 1 else None
    if kind is None:
        raise MuxError(
            f"Track {header.track_id} holds {header.handler!r}/{'+'.join(sorted(codecs))!r} "
            "data; only H.264 (avc1) or AV1 (av01) video and AAC (mp4a) audio can be muxed."
        )
    if flavor == "m4a" and kind == "video":
        raise MuxError("An M4A file holds only audio, but an input contains video.")
    if flavor == "mov" and "av01" in codecs:
        raise MuxError(
            "QuickTime .mov files cannot hold AV1 video.",
            suggestion="Download this video as .mp4, or with quality='compat' (H.264).",
        )
    return kind


def _media_track(
    flavor: Flavor,
    number: int,
    track: IndexedTrack,
    *,
    track_id: int,
    kind: TrackKind,
    lead: Fraction,
    enabled: bool,
) -> tuple[TrackPlan, _Layout]:
    header, samples = track.header, track.samples
    first_dts = samples.dts[0]
    dts = [value - first_dts for value in samples.dts]
    media_duration = dts[-1] + samples.durations[-1]
    presentation_end = max(
        decode + offset + duration
        for decode, offset, duration in zip(dts, samples.ctos, samples.durations, strict=True)
    )
    edits = convert_edits(
        header.edits,
        movie_timescale=header.movie_timescale,
        timescale=header.timescale,
        first_dts=first_dts,
        presentation_end=presentation_end,
        lead=lead,
    )
    entries = header.sample_entries
    if flavor == "mov" and kind == "audio":
        frame = Counter(samples.durations).most_common(1)[0][0]  # 1024 for AAC-LC
        entries = tuple(quicktime_sound_entry(entry, samples_per_packet=frame) for entry in entries)
    chunks = chunk_ranges(dts, samples.descriptions, span=_MEDIA_CHUNK_SECONDS * header.timescale)
    visual = kind == "video"
    plan = TrackPlan(
        track_id=track_id,
        kind=kind,
        timescale=header.timescale,
        language=unpack_language(header.language),
        tag=None,
        name=None,
        enabled=enabled,
        matrix=header.matrix,
        width=header.width if visual else 0,
        height=header.height if visual else 0,
        edits=edits,
        duration=(
            sum(edit.duration for edit in edits)
            if edits
            else _to_movie(presentation_end, header.timescale)
        ),
        media_duration=media_duration,
        sample_entries=entries,
        durations=samples.durations,
        ctos=samples.ctos,
        sync=samples.sync,
        sizes=samples.sizes,
        chunks=tuple((count, samples.descriptions[first]) for first, count in chunks),
    )
    times = [lead + Fraction(dts[first], header.timescale) for first, _ in chunks]
    return plan, _Layout(chunks, times, number, samples.offsets, samples.sizes)


def _interleave(layouts: list[_Layout]) -> tuple[list[CopyOp | Blob], list[list[int]]]:
    """The mdat payload in time order, and every chunk's offset from the payload's start."""
    order = sorted(
        (time, track, chunk)
        for track, layout in enumerate(layouts)
        for chunk, time in enumerate(layout.times)
    )
    ops: list[CopyOp | Blob] = []
    offsets = [[0] * len(layout.chunks) for layout in layouts]
    position = 0
    for _, track, chunk in order:
        layout = layouts[track]
        first, count = layout.chunks[chunk]
        offsets[track][chunk] = position
        for sample in range(first, first + count):
            position += _add_copy(
                ops, CopyOp(layout.source, layout.offsets[sample], layout.sizes[sample])
            )
    return ops, offsets


def _layout(flavor: Flavor, plans: list[TrackPlan], layouts: list[_Layout]) -> MuxPlan:
    ops, offsets = _interleave(layouts)
    size = sum(_op_size(op) for op in ops)
    ftyp = ftyp_box(flavor, {plan.sample_entries[0][4:8].decode("latin-1") for plan in plans})
    narrow = [False] * len(plans)
    zeros = [[0] * len(track_offsets) for track_offsets in offsets]
    base = len(ftyp) + len(moov_box(flavor, plans, zeros, narrow)) + 8
    if base + size > U32_MAX:
        raise MuxError("Files larger than 4 GiB are not supported yet.")
    shifted = [[offset + base for offset in track_offsets] for track_offsets in offsets]
    header = ftyp + moov_box(flavor, plans, shifted, narrow) + u32(size + 8) + b"mdat"
    return MuxPlan((Blob(header), *ops))


def _add_copy(ops: list[CopyOp | Blob], op: CopyOp) -> int:
    if op.size == 0:
        return 0
    last = ops[-1] if ops else None
    if (
        isinstance(last, CopyOp)
        and last.source == op.source
        and last.offset + last.size == op.offset
    ):
        ops[-1] = CopyOp(last.source, last.offset, last.size + op.size)
    else:
        ops.append(op)
    return op.size


def _op_size(op: CopyOp | Blob) -> int:
    return op.size if isinstance(op, CopyOp) else len(op.data)


def _to_movie(ticks: int, timescale: int) -> int:
    return -(-ticks * MOVIE_TIMESCALE // timescale)
