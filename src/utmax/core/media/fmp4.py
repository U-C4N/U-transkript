"""Index fragmented MP4 streams (YouTube's DASH format) without reading sample data.

:func:`index_fragments` walks the top-level boxes of one input, parses ``moov`` (tracks, sample
descriptions, edit lists, ``trex`` defaults) and every ``moof`` (``tfhd``, ``tfdt``, ``trun``)
into per-track sample tables. Rules follow ISO/IEC 14496-12 section 8.8: per-sample values fall
back from ``trun`` to ``tfhd`` to ``trex``; the data of a run starts at its ``data_offset`` from
the fragment's base, else right after the previous run; the base is the explicit
``base_data_offset``, else the ``moof`` start when ``default-base-is-moof`` is set, else the
``moof`` start for the first track fragment and the end of the previous one's data after that.
"""

from __future__ import annotations

import struct
from array import array
from bisect import bisect_right
from dataclasses import dataclass
from itertools import accumulate

from utmax.core.media.boxes import (
    ByteSource,
    Reader,
    child_boxes,
    find_child,
    iter_boxes,
    read_exact,
    require_child,
)
from utmax.errors import MuxError

__all__ = [
    "Edit",
    "IndexedTrack",
    "SampleTable",
    "TrackHeader",
    "index_fragments",
    "parse_elst",
    "parse_stsd",
]

_TFHD_BASE_DATA_OFFSET = 0x000001
_TFHD_DESCRIPTION_INDEX = 0x000002
_TFHD_DEFAULT_DURATION = 0x000008
_TFHD_DEFAULT_SIZE = 0x000010
_TFHD_DEFAULT_FLAGS = 0x000020
_TFHD_DURATION_IS_EMPTY = 0x010000
_TFHD_DEFAULT_BASE_IS_MOOF = 0x020000

_TRUN_DATA_OFFSET = 0x000001
_TRUN_FIRST_SAMPLE_FLAGS = 0x000004
_TRUN_FIELDS = (("duration", 0x000100), ("size", 0x000200), ("flags", 0x000400), ("cto", 0x000800))

# A sample is a sync sample unless it is flagged non-sync or "depends on others" (as FFmpeg).
_NOT_SYNC = 0x0101_0000


@dataclass(frozen=True, slots=True)
class Edit:
    """One edit list entry: ``duration`` in movie ticks, ``media_time`` (-1 = empty edit)."""

    duration: int
    media_time: int
    rate: int = 0x0001_0000


@dataclass(frozen=True, slots=True)
class TrackHeader:
    """What the ``moov`` box says about one track."""

    track_id: int
    handler: str
    timescale: int
    language: int
    matrix: bytes
    width: int
    height: int
    sample_entries: tuple[bytes, ...]
    edits: tuple[Edit, ...]
    movie_timescale: int

    @property
    def codec(self) -> str:
        """The four-character code of the first sample description, e.g. ``"avc1"``."""
        return self.sample_entries[0][4:8].decode("latin-1")


class SampleTable:
    """Parallel arrays with one entry per sample, in decode order."""

    __slots__ = ("ctos", "descriptions", "dts", "durations", "offsets", "sizes", "sync")

    def __init__(self) -> None:
        self.offsets: array[int] = array("q")
        self.sizes: array[int] = array("q")
        self.dts: array[int] = array("q")
        self.durations: array[int] = array("q")
        self.ctos: array[int] = array("q")
        self.sync = bytearray()
        self.descriptions: array[int] = array("q")

    def __len__(self) -> int:
        return len(self.sizes)


@dataclass(frozen=True, slots=True)
class IndexedTrack:
    """One track of a fragmented input: its header and every sample."""

    header: TrackHeader
    samples: SampleTable


@dataclass(frozen=True, slots=True)
class _Defaults:
    description: int
    duration: int
    size: int
    flags: int


_NO_DEFAULTS = _Defaults(description=1, duration=0, size=0, flags=0)


class _Indexer:
    def __init__(self, headers: dict[int, TrackHeader], defaults: dict[int, _Defaults]) -> None:
        self.headers = headers
        self.defaults = defaults
        self.tables = {track_id: SampleTable() for track_id in headers}
        self.next_dts: dict[int, int] = {}
        self.runs: list[tuple[int, int]] = []

    def moof(self, payload: bytes, moof_offset: int) -> None:
        implicit_base = moof_offset
        for kind, body in child_boxes(payload, context="moof"):
            if kind == "traf":
                implicit_base = self.traf(body, moof_offset, implicit_base)

    def traf(self, payload: bytes, moof_offset: int, implicit_base: int) -> int:
        children = child_boxes(payload, context="traf")
        tfhd = next((body for kind, body in children if kind == "tfhd"), None)
        if tfhd is None:
            raise MuxError("A track fragment has no 'tfhd' box.")
        reader = Reader(tfhd, "tfhd")
        reader.skip(1)
        flags = reader.u24()
        track_id = reader.u32()
        header = self.headers.get(track_id)
        if header is None:
            raise MuxError(f"A fragment refers to track {track_id}, which the moov box lacks.")
        trex = self.defaults.get(track_id, _NO_DEFAULTS)
        if flags & _TFHD_BASE_DATA_OFFSET:
            base = reader.u64()
        elif flags & _TFHD_DEFAULT_BASE_IS_MOOF:
            base = moof_offset
        else:
            base = implicit_base
        description = reader.u32() if flags & _TFHD_DESCRIPTION_INDEX else trex.description
        defaults = _Defaults(
            description=description,
            duration=reader.u32() if flags & _TFHD_DEFAULT_DURATION else trex.duration,
            size=reader.u32() if flags & _TFHD_DEFAULT_SIZE else trex.size,
            flags=reader.u32() if flags & _TFHD_DEFAULT_FLAGS else trex.flags,
        )
        if not 1 <= description <= len(header.sample_entries):
            raise MuxError(
                f"Track {track_id} uses sample description {description}, "
                f"but only {len(header.sample_entries)} exist."
            )
        table = self.tables[track_id]
        tfdt = next((body for kind, body in children if kind == "tfdt"), None)
        dts = self.next_dts.get(track_id, 0) if tfdt is None else _base_media_decode_time(tfdt)
        if len(table):
            gap = dts - table.dts[-1]
            if gap < 0:
                raise MuxError(f"Decode times go backwards in track {track_id}.")
            table.durations[-1] = gap
        position = base
        for kind, body in children:
            if kind == "trun":
                position, dts = self.trun(
                    body, base=base, position=position, dts=dts, defaults=defaults, table=table
                )
        if flags & _TFHD_DURATION_IS_EMPTY:
            dts += defaults.duration
        self.next_dts[track_id] = dts
        return position

    def trun(
        self,
        payload: bytes,
        *,
        base: int,
        position: int,
        dts: int,
        defaults: _Defaults,
        table: SampleTable,
    ) -> tuple[int, int]:
        reader = Reader(payload, "trun")
        reader.skip(1)  # version: offsets are read as signed either way
        flags = reader.u24()
        count = reader.u32()
        start = base + reader.i32() if flags & _TRUN_DATA_OFFSET else position
        first_flags = reader.u32() if flags & _TRUN_FIRST_SAMPLE_FLAGS else None
        names = [name for name, bit in _TRUN_FIELDS if flags & bit]
        width = len(names)
        if width * 4 * count > reader.remaining:
            raise MuxError(f"The 'trun' box lists {count} samples but is too short for them.")
        values = struct.unpack(f">{width * count}I", reader.take(width * 4 * count))
        columns = {name: values[index::width] for index, name in enumerate(names)}
        durations = columns.get("duration", [defaults.duration] * count)
        sizes = columns.get("size", [defaults.size] * count)
        if "flags" in columns:
            sample_flags = list(columns["flags"])
        else:
            sample_flags = [defaults.flags] * count
            if first_flags is not None and count:
                sample_flags[0] = first_flags
        # Composition offsets are signed in version 1; like FFmpeg, read version 0 the same way.
        ctos = [
            value - 0x1_0000_0000 if value & 0x8000_0000 else value
            for value in columns.get("cto", [0] * count)
        ]
        if start < 0:
            raise MuxError("A 'trun' box points before the start of the file.")
        offsets = list(accumulate(sizes, initial=start))
        decode_times = list(accumulate(durations, initial=dts))
        table.offsets.extend(offsets[:-1])
        table.sizes.extend(sizes)
        table.dts.extend(decode_times[:-1])
        table.durations.extend(durations)
        table.ctos.extend(ctos)
        table.sync.extend(0 if value & _NOT_SYNC else 1 for value in sample_flags)
        table.descriptions.extend([defaults.description] * count)
        self.runs.append((start, offsets[-1]))
        return offsets[-1], decode_times[-1]


def index_fragments(source: ByteSource) -> tuple[IndexedTrack, ...]:
    """Every track of a fragmented MP4 in ``source``, with all of its samples.

    Raises:
        MuxError: the input is not a fragmented MP4, is truncated or is inconsistent.
    """
    indexer: _Indexer | None = None
    mdats: list[tuple[int, int]] = []
    for header in iter_boxes(source):
        if header.kind == "moov":
            if indexer is not None:
                raise MuxError("The input has two 'moov' boxes.")
            payload = read_exact(source, header.payload_offset, header.payload_size)
            indexer = _Indexer(*_parse_moov(payload))
        elif header.kind == "moof":
            if indexer is None:
                raise MuxError("The input has a 'moof' box before its 'moov' box.")
            payload = read_exact(source, header.payload_offset, header.payload_size)
            indexer.moof(payload, header.offset)
        elif header.kind == "mdat":
            mdats.append((header.payload_offset, header.end))
    if indexer is None:
        raise MuxError("The input has no 'moov' box, so it is not an MP4 file.")
    _check_runs_inside_mdat(indexer.runs, mdats)
    tracks: list[IndexedTrack] = []
    for track_id, track_header in indexer.headers.items():
        table = indexer.tables[track_id]
        if not len(table):
            raise MuxError(f"Track {track_id} of the input has no samples.")
        tracks.append(IndexedTrack(track_header, table))
    return tuple(tracks)


def _parse_moov(payload: bytes) -> tuple[dict[int, TrackHeader], dict[int, _Defaults]]:
    mvhd = Reader(require_child(payload, "mvhd", context="moov"), "mvhd")
    version = mvhd.u8()
    mvhd.skip(3 + (16 if version == 1 else 8))
    movie_timescale = mvhd.u32()
    mvex = find_child(payload, "mvex", context="moov")
    if mvex is None:
        raise MuxError("The input is not a fragmented MP4: its 'moov' box has no 'mvex' box.")
    defaults: dict[int, _Defaults] = {}
    for kind, body in child_boxes(mvex, context="mvex"):
        if kind == "trex":
            reader = Reader(body, "trex")
            reader.skip(4)
            track_id = reader.u32()
            defaults[track_id] = _Defaults(reader.u32(), reader.u32(), reader.u32(), reader.u32())
    headers: dict[int, TrackHeader] = {}
    for kind, body in child_boxes(payload, context="moov"):
        if kind == "trak":
            header = _parse_trak(body, movie_timescale)
            if header.track_id in headers:
                raise MuxError(f"The input declares track {header.track_id} twice.")
            headers[header.track_id] = header
    if not headers:
        raise MuxError("The input's 'moov' box has no tracks.")
    return headers, defaults


def _parse_trak(payload: bytes, movie_timescale: int) -> TrackHeader:
    tkhd = Reader(require_child(payload, "tkhd", context="trak"), "tkhd")
    version = tkhd.u8()
    tkhd.skip(3 + (16 if version == 1 else 8))
    track_id = tkhd.u32()
    # reserved, duration, reserved, layer, alternate group, volume, reserved
    tkhd.skip(4 + (8 if version == 1 else 4) + 8 + 8)
    matrix = tkhd.take(36)
    width, height = tkhd.u32(), tkhd.u32()
    edits: tuple[Edit, ...] = ()
    edts = find_child(payload, "edts", context="trak")
    elst = find_child(edts, "elst", context="edts") if edts is not None else None
    if elst is not None:
        edits = parse_elst(elst)
    mdia = require_child(payload, "mdia", context="trak")
    mdhd = Reader(require_child(mdia, "mdhd", context="mdia"), "mdhd")
    version = mdhd.u8()
    mdhd.skip(3 + (16 if version == 1 else 8))
    timescale = mdhd.u32()
    mdhd.skip(8 if version == 1 else 4)
    language = mdhd.u16()
    if timescale == 0:
        raise MuxError(f"Track {track_id} has a zero timescale.")
    hdlr = Reader(require_child(mdia, "hdlr", context="mdia"), "hdlr")
    hdlr.skip(8)
    handler = hdlr.fourcc()
    minf = require_child(mdia, "minf", context="mdia")
    stbl = require_child(minf, "stbl", context="minf")
    stsz = find_child(stbl, "stsz", context="stbl")
    if stsz is not None:
        sizes = Reader(stsz, "stsz")
        sizes.skip(8)  # version, flags, shared sample size
        if sizes.u32():
            raise MuxError("The input keeps samples in its 'moov' box, which is not supported.")
    entries = parse_stsd(require_child(stbl, "stsd", context="stbl"))
    return TrackHeader(
        track_id=track_id,
        handler=handler,
        timescale=timescale,
        language=language,
        matrix=matrix,
        width=width,
        height=height,
        sample_entries=entries,
        edits=edits,
        movie_timescale=movie_timescale,
    )


def parse_stsd(payload: bytes) -> tuple[bytes, ...]:
    """The sample descriptions of an ``stsd`` payload, each as a complete box."""
    reader = Reader(payload, "stsd")
    reader.skip(4)
    count = reader.u32()
    entries: list[bytes] = []
    for _ in range(count):
        head = reader.take(8)
        (size,) = struct.unpack(">I", head[:4])
        if size < 8:
            raise MuxError("A sample description has an impossible size.")
        entries.append(head + reader.take(size - 8))
    if not entries:
        raise MuxError("A track has no sample descriptions.")
    return tuple(entries)


def parse_elst(payload: bytes) -> tuple[Edit, ...]:
    """The entries of an ``elst`` payload (version 0 or 1)."""
    reader = Reader(payload, "elst")
    version = reader.u8()
    reader.skip(3)
    edits: list[Edit] = []
    for _ in range(reader.u32()):
        if version == 1:
            duration, media_time = reader.u64(), reader.i64()
        else:
            duration, media_time = reader.u32(), reader.i32()
        edits.append(Edit(duration, media_time, reader.u32()))
    return tuple(edits)


def _base_media_decode_time(payload: bytes) -> int:
    reader = Reader(payload, "tfdt")
    version = reader.u8()
    reader.skip(3)
    return reader.u64() if version == 1 else reader.u32()


def _check_runs_inside_mdat(runs: list[tuple[int, int]], mdats: list[tuple[int, int]]) -> None:
    mdats.sort()
    starts = [start for start, _ in mdats]
    for start, end in runs:
        if end <= start:
            continue
        index = bisect_right(starts, start) - 1
        if index < 0 or end > mdats[index][1]:
            raise MuxError(f"Sample data at bytes {start}-{end} lies outside every 'mdat' box.")
