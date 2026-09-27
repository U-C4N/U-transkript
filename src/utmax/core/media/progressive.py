"""Read progressive (non-fragmented) MP4/MOV files: layout, track headers and every sample.

The muxer's tests re-parse its output with this module, so it understands everything the
muxer writes: ``co64``, 64-bit ``mdat`` sizes, ``ctts`` version 1, ``elng``, ``udta/name`` and
QuickTime's Pascal-string handler names.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate

from utmax.core.media.boxes import (
    BoxHeader,
    ByteSource,
    Reader,
    child_boxes,
    find_child,
    iter_boxes,
    read_exact,
    require_child,
)
from utmax.core.media.fmp4 import Edit, parse_elst, parse_stsd
from utmax.errors import MuxError

__all__ = ["Chunk", "ProgressiveFile", "Sample", "Track", "parse_progressive"]


@dataclass(frozen=True, slots=True)
class Sample:
    """One sample: where its bytes are and when it is decoded and shown."""

    offset: int
    size: int
    dts: int
    duration: int
    cto: int
    sync: bool
    description: int


@dataclass(frozen=True, slots=True)
class Chunk:
    """A run of samples stored back to back."""

    offset: int
    first_sample: int
    count: int
    description: int


@dataclass(frozen=True, slots=True)
class Track:
    """One ``trak`` box, decoded."""

    track_id: int
    flags: int
    alternate_group: int
    volume: int
    width: int
    height: int
    duration: int
    edits: tuple[Edit, ...]
    handler: str
    handler_name: str
    timescale: int
    media_duration: int
    language: int
    extended_language: str | None
    name: str | None
    media_header: str
    data_handler: bool
    sample_entries: tuple[bytes, ...]
    chunk_box: str
    ctts_version: int | None
    chunks: tuple[Chunk, ...]
    samples: tuple[Sample, ...]


@dataclass(frozen=True, slots=True)
class ProgressiveFile:
    """A whole file: brands, top-level boxes, movie header and tracks."""

    major_brand: str
    minor_version: int
    compatible_brands: tuple[str, ...]
    boxes: tuple[BoxHeader, ...]
    timescale: int
    duration: int
    next_track_id: int
    tracks: tuple[Track, ...]


def parse_progressive(source: ByteSource) -> ProgressiveFile:
    """Decode a progressive MP4/MOV file.

    Raises:
        MuxError: a required box is missing or the sample tables disagree.
    """
    boxes = tuple(iter_boxes(source))
    ftyp = _payload(source, boxes, "ftyp")
    moov = _payload(source, boxes, "moov")
    brands = Reader(ftyp, "ftyp")
    major, minor = brands.fourcc(), brands.u32()
    compatible = tuple(
        ftyp[offset : offset + 4].decode("latin-1") for offset in range(8, len(ftyp), 4)
    )
    mvhd = Reader(require_child(moov, "mvhd", context="moov"), "mvhd")
    version = mvhd.u8()
    mvhd.skip(3 + (16 if version == 1 else 8))
    timescale = mvhd.u32()
    duration = mvhd.u64() if version == 1 else mvhd.u32()
    mvhd.skip(4 + 2 + 10 + 36 + 24)
    next_track_id = mvhd.u32()
    tracks = tuple(
        _track(body, quicktime=major == "qt  ")
        for kind, body in child_boxes(moov, context="moov")
        if kind == "trak"
    )
    return ProgressiveFile(
        major, minor, compatible, boxes, timescale, duration, next_track_id, tracks
    )


def _payload(source: ByteSource, boxes: Sequence[BoxHeader], kind: str) -> bytes:
    header = next((header for header in boxes if header.kind == kind), None)
    if header is None:
        raise MuxError(f"The file has no top-level {kind!r} box.")
    return read_exact(source, header.payload_offset, header.payload_size)


def _track(payload: bytes, *, quicktime: bool) -> Track:
    tkhd = Reader(require_child(payload, "tkhd", context="trak"), "tkhd")
    version = tkhd.u8()
    flags = tkhd.u24()
    tkhd.skip(16 if version == 1 else 8)
    track_id = tkhd.u32()
    tkhd.skip(4)
    duration = tkhd.u64() if version == 1 else tkhd.u32()
    tkhd.skip(8 + 2)
    alternate_group, volume = tkhd.u16(), tkhd.u16()
    tkhd.skip(2 + 36)
    width, height = tkhd.u32(), tkhd.u32()
    edts = find_child(payload, "edts", context="trak")
    elst = find_child(edts, "elst", context="edts") if edts is not None else None
    mdia = require_child(payload, "mdia", context="trak")
    mdhd = Reader(require_child(mdia, "mdhd", context="mdia"), "mdhd")
    version = mdhd.u8()
    mdhd.skip(3 + (16 if version == 1 else 8))
    timescale = mdhd.u32()
    media_duration = mdhd.u64() if version == 1 else mdhd.u32()
    language = mdhd.u16()
    hdlr = require_child(mdia, "hdlr", context="mdia")
    elng = find_child(mdia, "elng", context="mdia")
    minf = require_child(mdia, "minf", context="mdia")
    minf_kinds = [kind for kind, _ in child_boxes(minf, context="minf")]
    udta = find_child(payload, "udta", context="trak")
    name = find_child(udta, "name", context="udta") if udta is not None else None
    stbl = require_child(minf, "stbl", context="minf")
    chunk_box = "co64" if find_child(stbl, "co64", context="stbl") is not None else "stco"
    ctts = find_child(stbl, "ctts", context="stbl")
    chunks, samples = _samples(stbl, chunk_box)
    return Track(
        track_id=track_id,
        flags=flags,
        alternate_group=alternate_group,
        volume=volume,
        width=width,
        height=height,
        duration=duration,
        edits=parse_elst(elst) if elst is not None else (),
        handler=hdlr[8:12].decode("latin-1"),
        handler_name=_handler_name(hdlr[24:], quicktime=quicktime),
        timescale=timescale,
        media_duration=media_duration,
        language=language,
        extended_language=elng[4:].split(b"\x00")[0].decode("ascii") if elng else None,
        name=name.decode("utf-8") if name is not None else None,
        media_header=next(kind for kind in minf_kinds if kind.endswith("hd")),
        data_handler="hdlr" in minf_kinds,
        sample_entries=parse_stsd(require_child(stbl, "stsd", context="stbl")),
        chunk_box=chunk_box,
        ctts_version=ctts[0] if ctts is not None else None,
        chunks=chunks,
        samples=samples,
    )


def _handler_name(raw: bytes, *, quicktime: bool) -> str:
    if quicktime and raw and raw[0] == len(raw) - 1:
        return raw[1:].decode("utf-8")
    return raw.split(b"\x00")[0].decode("utf-8")


def _samples(stbl: bytes, chunk_box: str) -> tuple[tuple[Chunk, ...], tuple[Sample, ...]]:
    durations = [
        duration for count, duration in _pairs(stbl, "stts", signed=False) for _ in range(count)
    ]
    count = len(durations)
    ctts = find_child(stbl, "ctts", context="stbl")
    ctos = (
        [offset for n, offset in _pairs(stbl, "ctts", signed=ctts[0] == 1) for _ in range(n)]
        if ctts is not None
        else [0] * count
    )
    stss = find_child(stbl, "stss", context="stbl")
    sync_numbers = set(_numbers(stss, "stss")) if stss is not None else None
    stsz = Reader(require_child(stbl, "stsz", context="stbl"), "stsz")
    stsz.skip(4)
    uniform, listed = stsz.u32(), stsz.u32()
    sizes = [uniform] * listed if uniform else [stsz.u32() for _ in range(listed)]
    offsets = _numbers(require_child(stbl, chunk_box, context="stbl"), chunk_box)
    if not (len(ctos) == len(sizes) == count):
        raise MuxError("The sample tables disagree about the number of samples.")
    per_chunk = _expand_stsc(require_child(stbl, "stsc", context="stbl"), len(offsets))
    chunks: list[Chunk] = []
    samples: list[Sample] = []
    decode_times = list(accumulate(durations, initial=0))
    for chunk_offset, (samples_in_chunk, description) in zip(offsets, per_chunk, strict=True):
        chunks.append(Chunk(chunk_offset, len(samples), samples_in_chunk, description))
        position = chunk_offset
        for _ in range(samples_in_chunk):
            index = len(samples)
            if index >= count:
                raise MuxError("The chunk tables list more samples than the sample tables.")
            samples.append(
                Sample(
                    offset=position,
                    size=sizes[index],
                    dts=decode_times[index],
                    duration=durations[index],
                    cto=ctos[index],
                    sync=sync_numbers is None or index + 1 in sync_numbers,
                    description=description,
                )
            )
            position += sizes[index]
    if len(samples) != count:
        raise MuxError("The chunk tables list fewer samples than the sample tables.")
    return tuple(chunks), tuple(samples)


def _pairs(stbl: bytes, kind: str, *, signed: bool) -> list[tuple[int, int]]:
    reader = Reader(require_child(stbl, kind, context="stbl"), kind)
    reader.skip(4)
    return [(reader.u32(), reader.i32() if signed else reader.u32()) for _ in range(reader.u32())]


def _numbers(payload: bytes, kind: str) -> list[int]:
    reader = Reader(payload, kind)
    reader.skip(4)
    count = reader.u32()
    return [reader.u64() if kind == "co64" else reader.u32() for _ in range(count)]


def _expand_stsc(payload: bytes, chunk_count: int) -> list[tuple[int, int]]:
    reader = Reader(payload, "stsc")
    reader.skip(4)
    entries = [(reader.u32(), reader.u32(), reader.u32()) for _ in range(reader.u32())]
    expanded: list[tuple[int, int]] = []
    for index, (first, samples, description) in enumerate(entries):
        last = entries[index + 1][0] - 1 if index + 1 < len(entries) else chunk_count
        expanded.extend((samples, description) for _ in range(first, last + 1))
    if len(expanded) != chunk_count:
        raise MuxError("The 'stsc' box does not match the number of chunks.")
    return expanded
