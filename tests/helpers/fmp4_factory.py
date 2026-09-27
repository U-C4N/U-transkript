"""Build synthetic fragmented MP4 files for tests, down to every tfhd and trun flag.

A test lists each track's samples and how every fragment encodes them; the factory computes
the offsets and writes the boxes. It refuses specs a real muxer could not produce (a trun that
omits sample sizes while the samples differ from the default size, for example), so the
samples in a spec are exactly what a correct parser must report. Every sample is filled with
an 8-byte pattern unique to (track, sample number); :func:`virtual_file` returns a ByteSource
that computes payloads on demand, for multi-gigabyte inputs that are never allocated.
"""

from __future__ import annotations

import struct
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate

from utmax.core.media.boxes import box, full_box, i16, i32, u16, u32, u64

SYNC_FLAGS = 0x0200_0000  # sample_depends_on = 2: decodable on its own
NON_SYNC_FLAGS = 0x0101_0000  # depends on other samples, flagged non-sync
UNITY = b"".join(u32(value) for value in (0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x4000_0000))
AVCC = bytes.fromhex(
    "01640028ffe1001e67640028acd100780227e5c05a808080a0000003002000000641e306224001000468ebef2c"
)
AV1C = bytes.fromhex("81080c000a0e00000042abbfc377ebe240404041")
ESDS = bytes.fromhex(
    "000000000327000100041f40150000000000000000000000051012100000000000000000000000000000060102"
)


@dataclass(frozen=True)
class Sample:
    """What a parser must report for one sample."""

    duration: int
    size: int
    sync: bool = True
    cto: int = 0


@dataclass(frozen=True)
class Track:
    """One track of the init segment."""

    track_id: int = 1
    handler: str = "vide"
    codec: str = "avc1"
    timescale: int = 12800
    language: str = "und"
    width: int = 640
    height: int = 360
    edits: tuple[tuple[int, int], ...] = ()  # (duration in movie ticks, media time)
    entries: int = 1
    trex: tuple[int, int, int, int] = (1, 0, 0, 0)  # description, duration, size, flags
    channels: int = 2
    sample_rate: int = 44100
    extra_audio_box: bytes = b""


@dataclass(frozen=True)
class Run:
    """One trun box."""

    samples: tuple[Sample, ...]
    flags: int = 0x000F01  # data offset + per-sample duration, size, flags and cto
    version: int = 0
    shift: int = 0  # added to the written data_offset, to break a file on purpose


@dataclass(frozen=True)
class Traf:
    """One track fragment: tfhd flags and defaults, tfdt and runs."""

    track_id: int
    runs: tuple[Run, ...]
    flags: int = 0x020000  # default-base-is-moof
    description: int = 1
    default_duration: int = 0
    default_size: int = 0
    default_flags: int = 0
    tfdt: int | None = 0
    tfdt_version: int = 0


@dataclass(frozen=True)
class _Payload:
    track_id: int
    first_index: int
    sizes: tuple[int, ...]


def payload(track_id: int, index: int, size: int) -> bytes:
    """The bytes the factory stores for sample ``index`` of ``track_id``."""
    pattern = struct.pack(">HIH", track_id, index, 0xA55A)
    return (pattern * (size // 8 + 1))[:size]


def sample_entry(track: Track) -> bytes:
    """A plausible sample description for ``track.codec``."""
    if track.codec in ("avc1", "av01"):
        config = box("avcC", AVCC) if track.codec == "avc1" else box("av1C", AV1C)
        return box(
            track.codec,
            bytes(6),
            u16(1),
            bytes(16),
            u16(track.width),
            u16(track.height),
            u32(0x0048_0000),
            u32(0x0048_0000),
            u32(0),
            u16(1),
            bytes(32),
            u16(0x0018),
            i16(-1),
            config,
        )
    if track.codec == "mp4a":
        return box(
            "mp4a",
            bytes(6),
            u16(1),
            bytes(8),
            u16(track.channels),
            u16(16),
            u32(0),
            u32((track.sample_rate << 16) & 0xFFFF_FFFF),
            box("esds", ESDS),
            track.extra_audio_box,
        )
    return box(track.codec, bytes(6), u16(1), bytes(70))


def init_segment(
    tracks: Sequence[Track],
    *,
    movie_timescale: int = 1000,
    fragmented: bool = True,
    samples_in_moov: bool = False,
    header_version: int = 0,
    mvex_extra: bytes = b"",
) -> bytes:
    """``ftyp`` + ``moov`` (``mvex`` unless ``fragmented`` is false)."""
    wide = header_version == 1
    mvhd = full_box(
        "mvhd",
        header_version,
        0,
        bytes(16 if wide else 8),
        u32(movie_timescale),
        u64(0) if wide else u32(0),
        u32(0x10000),
        u16(0x100),
        bytes(10),
        UNITY,
        bytes(24),
        u32(len(tracks) + 1),
    )
    parts = [mvhd]
    parts += [_trak(track, samples_in_moov=samples_in_moov, wide=wide) for track in tracks]
    if fragmented:
        trex = [
            full_box("trex", 0, 0, u32(track.track_id), *(u32(value) for value in track.trex))
            for track in tracks
        ]
        parts.append(box("mvex", mvex_extra, *trex))
    return box("ftyp", b"dash", u32(0), b"iso6", b"mp41") + box("moov", *parts)


def fragmented_file(
    tracks: Sequence[Track],
    fragments: Sequence[Sequence[Traf]],
    *,
    movie_timescale: int = 1000,
    after_moov: bytes = b"",
    between: bytes = b"",
    header_version: int = 0,
) -> bytes:
    """A complete fragmented MP4 in memory."""
    init = init_segment(tracks, movie_timescale=movie_timescale, header_version=header_version)
    pieces = _pieces(init + after_moov, tracks, fragments, between)
    return b"".join(p if isinstance(p, bytes) else _materialize(p) for p in pieces)


def virtual_file(
    tracks: Sequence[Track], fragments: Sequence[Sequence[Traf]], *, movie_timescale: int = 1000
) -> VirtualSource:
    """Like :func:`fragmented_file`, but payload bytes are only computed when read."""
    init = init_segment(tracks, movie_timescale=movie_timescale)
    return VirtualSource(_pieces(init, tracks, fragments, b""))


def simple_file(
    samples: Sequence[Sample],
    *,
    track: Track | None = None,
    per_fragment: int = 10,
    run_flags: int = 0x000F01,
    run_version: int = 0,
) -> bytes:
    """One track in fragments of ``per_fragment`` samples, one run each, with tfdt."""
    spec = track or Track()
    fragments: list[list[Traf]] = []
    decode_time = 0
    for start in range(0, len(samples), per_fragment):
        chunk = tuple(samples[start : start + per_fragment])
        run = Run(chunk, flags=run_flags, version=run_version)
        fragments.append([Traf(spec.track_id, (run,), tfdt=decode_time)])
        decode_time += sum(sample.duration for sample in chunk)
    return fragmented_file([spec], fragments)


class VirtualSource:
    """A ByteSource whose sample payloads are computed on demand."""

    def __init__(self, pieces: list[bytes | _Payload]) -> None:
        self._pieces = pieces
        lengths = [len(p) if isinstance(p, bytes) else sum(p.sizes) for p in pieces]
        self._starts = list(accumulate(lengths, initial=0))
        self.size = self._starts[-1]

    def read(self, offset: int, n: int) -> bytes:
        end = min(offset + n, self.size)
        out = bytearray()
        index = bisect_right(self._starts, offset) - 1
        while offset < end:
            piece, start = self._pieces[index], self._starts[index]
            take = min(end, self._starts[index + 1]) - offset
            if isinstance(piece, bytes):
                out += piece[offset - start : offset - start + take]
            else:
                out += _payload_window(piece, offset - start, take)
            offset += take
            index += 1
        return bytes(out)


def _payload_window(piece: _Payload, offset: int, n: int) -> bytes:
    starts = list(accumulate(piece.sizes, initial=0))
    out = bytearray()
    while n > 0:
        sample = bisect_right(starts, offset) - 1
        within = offset - starts[sample]
        take = min(n, piece.sizes[sample] - within)
        pattern = struct.pack(">HIH", piece.track_id, piece.first_index + sample, 0xA55A)
        repeated = pattern * ((within % 8 + take) // 8 + 1)
        out += repeated[within % 8 : within % 8 + take]
        offset += take
        n -= take
    return bytes(out)


def _materialize(piece: _Payload) -> bytes:
    return b"".join(
        payload(piece.track_id, piece.first_index + index, size)
        for index, size in enumerate(piece.sizes)
    )


def _pieces(
    head: bytes, tracks: Sequence[Track], fragments: Sequence[Sequence[Traf]], between: bytes
) -> list[bytes | _Payload]:
    by_id = {track.track_id: track for track in tracks}
    pieces: list[bytes | _Payload] = [head]
    position = len(head)
    counters = dict.fromkeys(by_id, 0)
    for number, trafs in enumerate(fragments, start=1):
        if number > 1 and between:
            pieces.append(between)
            position += len(between)
        payloads: list[_Payload] = []
        for traf in trafs:
            for run in traf.runs:
                sizes = tuple(sample.size for sample in run.samples)
                payloads.append(_Payload(traf.track_id, counters[traf.track_id], sizes))
                counters[traf.track_id] += len(sizes)
        data_size = sum(sum(p.sizes) for p in payloads)
        if data_size + 8 <= 0xFFFF_FFFF:
            header = u32(data_size + 8) + b"mdat"
        else:
            header = u32(1) + b"mdat" + u64(data_size + 16)
        draft = _moof(number, trafs, by_id, moof_start=position, data_start=None)
        data_start = position + len(draft) + len(header)
        moof = _moof(number, trafs, by_id, moof_start=position, data_start=data_start)
        pieces += [moof, header, *payloads]
        position += len(moof) + len(header) + data_size
    return pieces


def _moof(
    number: int,
    trafs: Sequence[Traf],
    tracks: dict[int, Track],
    *,
    moof_start: int,
    data_start: int | None,
) -> bytes:
    """The moof box; ``data_start=None`` drafts it (same size, offsets not yet known)."""
    draft = data_start is None
    boxes = [full_box("mfhd", 0, 0, u32(number))]
    position = data_start or 0
    previous_end = moof_start
    for traf in trafs:
        track = tracks[traf.track_id]
        if traf.flags & 0x000001:
            base = position if draft else data_start or 0
        elif traf.flags & 0x020000:
            base = moof_start
        else:
            base = previous_end
        fields = [u32(traf.track_id)]
        if traf.flags & 0x000001:
            fields.append(u64(base))
        for bit, value in (
            (0x000002, traf.description),
            (0x000008, traf.default_duration),
            (0x000010, traf.default_size),
            (0x000020, traf.default_flags),
        ):
            if traf.flags & bit:
                fields.append(u32(value))
        children = [full_box("tfhd", 0, traf.flags, *fields)]
        if traf.tfdt is not None:
            decode_time = u64(traf.tfdt) if traf.tfdt_version else u32(traf.tfdt)
            children.append(full_box("tfdt", traf.tfdt_version, 0, decode_time))
        defaults = (
            traf.default_duration if traf.flags & 0x000008 else track.trex[1],
            traf.default_size if traf.flags & 0x000010 else track.trex[2],
            traf.default_flags if traf.flags & 0x000020 else track.trex[3],
        )
        expected = base
        for run in traf.runs:
            if not draft and not run.flags & 0x000001 and position != expected:
                raise AssertionError("a run without data_offset must start where the last ended")
            offset = 0 if draft else position - base + run.shift
            children.append(_trun(run, data_offset=offset, defaults=defaults))
            position += sum(sample.size for sample in run.samples)
            expected = position
        previous_end = position
        boxes.append(box("traf", *children))
    return box("moof", *boxes)


def _trun(run: Run, *, data_offset: int, defaults: tuple[int, int, int]) -> bytes:
    default_duration, default_size, default_flags = defaults
    fields = [u32(len(run.samples))]
    if run.flags & 0x000001:
        fields.append(i32(data_offset))
    if run.flags & 0x000004:
        fields.append(u32(_flags(run.samples[0])))
    for index, sample in enumerate(run.samples):
        if run.flags & 0x000100:
            fields.append(u32(sample.duration))
        elif sample.duration != default_duration:
            raise AssertionError("an omitted duration must equal the default duration")
        if run.flags & 0x000200:
            fields.append(u32(sample.size))
        elif sample.size != default_size:
            raise AssertionError("an omitted size must equal the default size")
        if run.flags & 0x000400:
            fields.append(u32(_flags(sample)))
        else:
            first = index == 0 and run.flags & 0x000004
            implied = _flags(sample) if first else default_flags
            if (not implied & 0x0101_0000) != sample.sync:
                raise AssertionError("omitted sample flags must match the sample's sync state")
        if run.flags & 0x000800:
            fields.append(i32(sample.cto))
        elif sample.cto:
            raise AssertionError("an omitted composition offset must be zero")
    return full_box("trun", run.version, run.flags, *fields)


def _flags(sample: Sample) -> int:
    return SYNC_FLAGS if sample.sync else NON_SYNC_FLAGS


def _trak(track: Track, *, samples_in_moov: bool, wide: bool) -> bytes:
    visual = track.handler == "vide"
    tkhd = full_box(
        "tkhd",
        1 if wide else 0,
        3,
        bytes(16 if wide else 8),
        u32(track.track_id),
        u32(0),
        u64(0) if wide else u32(0),
        bytes(8),
        u16(0),
        u16(0 if visual else 1),
        u16(0 if visual else 0x100),
        u16(0),
        UNITY,
        u32(track.width << 16 if visual else 0),
        u32(track.height << 16 if visual else 0),
    )
    parts = [tkhd]
    if track.edits:
        entries = [
            u32(length) + i32(media_time) + u32(0x10000) for length, media_time in track.edits
        ]
        parts.append(box("edts", full_box("elst", 0, 0, u32(len(entries)), *entries)))
    language = 0
    for letter in track.language:
        language = language << 5 | (ord(letter) - 0x60)
    mdhd = full_box(
        "mdhd",
        1 if wide else 0,
        0,
        bytes(16 if wide else 8),
        u32(track.timescale),
        u64(0) if wide else u32(0),
        u16(language),
        u16(0),
    )
    hdlr = full_box("hdlr", 0, 0, u32(0), track.handler.encode("ascii"), bytes(12), b"Handler\x00")
    header = full_box("vmhd", 0, 1, bytes(8)) if visual else full_box("smhd", 0, 0, bytes(4))
    dinf = box("dinf", full_box("dref", 0, 0, u32(1), full_box("url ", 0, 1)))
    stbl = box(
        "stbl",
        full_box("stsd", 0, 0, u32(track.entries), *[sample_entry(track)] * track.entries),
        full_box("stts", 0, 0, u32(0)),
        full_box("stsc", 0, 0, u32(0)),
        full_box("stsz", 0, 0, u32(0), u32(1 if samples_in_moov else 0)),
        full_box("stco", 0, 0, u32(0)),
    )
    parts.append(box("mdia", mdhd, hdlr, box("minf", header, dinf, stbl)))
    return box("trak", *parts)
