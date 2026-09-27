"""The ``ftyp`` and ``moov`` boxes of progressive MP4, MOV and M4A files.

Layouts follow ISO/IEC 14496-12 and Apple's QuickTime File Format; field values follow
FFmpeg's ``libavformat/movenc.c`` (b87602a63a52): tkhd flags "in movie" plus "enabled",
alternate group = media type (video 0, audio 1, subtitle 3), handler names "VideoHandler" and
"SoundHandler", ``mdhd``/``tkhd``/``mvhd`` version 1 only from 2^31 - 1 ticks, zero creation
times. Flavor differences: MOV uses Pascal-string handler names, a ``dhlr`` data handler in
``minf``, Macintosh language codes when one exists, and a SoundDescription version 1 audio
entry with a ``wave`` box; MP4 and M4A keep the source audio entry and C-string names.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from utmax.core.languages import mac_language_code
from utmax.core.media.boxes import (
    I32_MAX,
    Reader,
    box,
    find_child,
    full_box,
    i16,
    u8,
    u16,
    u32,
    u64,
)
from utmax.core.media.fmp4 import Edit
from utmax.core.media.tables import (
    chunk_offsets_box,
    ctts_box,
    edts_box,
    stsc_box,
    stss_box,
    stsz_box,
    stts_box,
)
from utmax.errors import MuxError

__all__ = [
    "MOVIE_TIMESCALE",
    "UNITY_MATRIX",
    "Flavor",
    "TrackKind",
    "TrackPlan",
    "ftyp_box",
    "moov_box",
    "pack_language",
    "quicktime_sound_entry",
    "unpack_language",
]

Flavor = Literal["mp4", "mov", "m4a"]
TrackKind = Literal["video", "audio", "subtitle"]

MOVIE_TIMESCALE = 1000
UNITY_MATRIX = b"".join(u32(value) for value in (0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x4000_0000))

_HANDLERS: dict[TrackKind, str] = {"video": "vide", "audio": "soun", "subtitle": "sbtl"}
_HANDLER_NAMES: dict[TrackKind, str] = {"video": "VideoHandler", "audio": "SoundHandler"}
_ALTERNATE_GROUPS: dict[TrackKind, int] = {"video": 0, "audio": 1, "subtitle": 3}
_TKHD_ENABLED = 0x1
_TKHD_IN_MOVIE = 0x2
_DATA_HANDLER = full_box("hdlr", 0, 0, b"dhlr", b"url ", bytes(12), u8(11), b"DataHandler")
_DATA_INFORMATION = box("dinf", full_box("dref", 0, 0, u32(1), full_box("url ", 0, 1)))


@dataclass(frozen=True, slots=True)
class TrackPlan:
    """Everything needed to write one ``trak`` box except its chunk offsets."""

    track_id: int
    kind: TrackKind
    timescale: int
    language: str
    tag: str | None
    name: str | None
    enabled: bool
    matrix: bytes
    width: int
    height: int
    edits: tuple[Edit, ...]
    duration: int
    media_duration: int
    sample_entries: tuple[bytes, ...]
    durations: Sequence[int]
    ctos: Sequence[int]
    sync: bytes | bytearray
    sizes: Sequence[int]
    chunks: tuple[tuple[int, int], ...]


def ftyp_box(flavor: Flavor, codecs: Collection[str]) -> bytes:
    """``isom`` (+ ``iso2``, ``avc1``/``av01``, ``mp41``), ``qt  `` or ``M4A `` brands."""
    if flavor == "mov":
        return box("ftyp", b"qt  ", u32(0x200), b"qt  ")
    if flavor == "m4a":
        return box("ftyp", b"M4A ", u32(0x200), b"M4A ", b"isom", b"iso2", b"mp41")
    brands = [b"isom", b"iso2"]
    brands += [codec.encode("ascii") for codec in ("avc1", "av01") if codec in codecs]
    return box("ftyp", b"isom", u32(0x200), *brands, b"mp41")


def moov_box(
    flavor: Flavor,
    tracks: Sequence[TrackPlan],
    offsets: Sequence[Sequence[int]],
    wide: Sequence[bool],
) -> bytes:
    """The ``moov`` box: ``mvhd`` and one ``trak`` per track, with the given chunk offsets."""
    duration = max(track.duration for track in tracks)
    version = _version(flavor, duration)
    mvhd = full_box(
        "mvhd",
        version,
        0,
        bytes(16 if version else 8),  # creation and modification time
        u32(MOVIE_TIMESCALE),
        u64(duration) if version else u32(duration),
        u32(0x0001_0000),  # preferred rate 1.0
        u16(0x0100),  # preferred volume 1.0
        bytes(10),
        UNITY_MATRIX,
        bytes(24),  # QuickTime preview, poster, selection and current times
        u32(len(tracks) + 1),  # next track ID
    )
    traks = [
        _trak(flavor, track, track_offsets, track_wide)
        for track, track_offsets, track_wide in zip(tracks, offsets, wide, strict=True)
    ]
    return box("moov", mvhd, *traks)


def pack_language(code: str) -> int:
    """An ISO 639-2/T code as the 15-bit ``mdhd`` field (three 5-bit letters); bad -> ``und``."""
    if len(code) != 3 or not (code.isascii() and code.isalpha() and code.islower()):
        code = "und"
    value = 0
    for letter in code:
        value = value << 5 | (ord(letter) - 0x60)
    return value


def unpack_language(value: int) -> str:
    """The ISO 639-2/T code in an ``mdhd`` language field (``und`` for QuickTime codes)."""
    if value < 0x400:
        return "und"
    return "".join(chr(((value >> shift) & 0x1F) + 0x60) for shift in (10, 5, 0))


def quicktime_sound_entry(entry: bytes, *, samples_per_packet: int) -> bytes:
    """An ISO ``mp4a`` sample entry as a QuickTime SoundDescription version 1.

    The AAC configuration moves into a ``wave`` box (``frma``, ``mp4a``, ``esds``, terminator),
    as FFmpeg writes it for ``.mov`` files.

    Raises:
        MuxError: more than two channels or a rate above 65535 Hz (not representable in a
            version 1 SoundDescription).
    """
    reader = Reader(entry, "mp4a")
    reader.skip(8 + 6)  # box header, reserved
    reference = reader.u16()
    version = reader.u16()
    reader.skip(6)  # revision level, vendor
    channels = reader.u16()
    reader.skip(6)  # sample size, compression ID, packet size
    rate = reader.u32()
    if version == 1:
        reader.skip(16)
    elif version != 0:
        raise MuxError(f"The AAC stream uses an unsupported sample description (v{version}).")
    extensions = reader.rest()
    esds = find_child(extensions, "esds", context="mp4a")
    if esds is None:
        raise MuxError("The AAC stream has no 'esds' decoder configuration.")
    too_fast = rate >> 16 == 0 or find_child(extensions, "srat", context="mp4a") is not None
    if not 1 <= channels <= 2 or too_fast:
        raise MuxError(
            "QuickTime .mov files made by utmax hold mono or stereo audio up to 65535 Hz; "
            "this stream needs .mp4 or .m4a.",
            suggestion="Download this video as .mp4 instead of .mov.",
        )
    wave = box("wave", box("frma", b"mp4a"), box("mp4a", u32(0)), box("esds", esds), u32(8), u32(0))
    return box(
        "mp4a",
        bytes(6),
        u16(reference),
        u16(1),  # SoundDescription version 1
        u16(0),  # revision level
        u32(0),  # vendor
        u16(channels),
        u16(16),  # sample size
        i16(-2),  # compression ID: variable bit rate
        u16(0),  # packet size
        u32(rate),
        u32(samples_per_packet),
        u32(0),  # bytes per packet
        u32(0),  # bytes per frame
        u32(2),  # bytes per sample
        wave,
    )


def _trak(flavor: Flavor, track: TrackPlan, offsets: Sequence[int], wide: bool) -> bytes:
    version = _version(flavor, track.duration)
    tkhd = full_box(
        "tkhd",
        version,
        _TKHD_IN_MOVIE | (_TKHD_ENABLED if track.enabled else 0),
        bytes(16 if version else 8),  # creation and modification time
        u32(track.track_id),
        u32(0),
        u64(track.duration) if version else u32(track.duration),
        bytes(8),
        u16(0),  # layer
        u16(_ALTERNATE_GROUPS[track.kind]),
        u16(0x0100 if track.kind == "audio" else 0),  # volume
        u16(0),
        track.matrix,
        u32(track.width),
        u32(track.height),
    )
    parts = [tkhd]
    if track.edits:
        parts.append(edts_box(track.edits))
    parts.append(_mdia(flavor, track, offsets, wide))
    if track.name:
        parts.append(box("udta", box("name", track.name.encode("utf-8"))))
    return box("trak", *parts)


def _mdia(flavor: Flavor, track: TrackPlan, offsets: Sequence[int], wide: bool) -> bytes:
    version = _version(flavor, track.media_duration)
    mdhd = full_box(
        "mdhd",
        version,
        0,
        bytes(16 if version else 8),  # creation and modification time
        u32(track.timescale),
        u64(track.media_duration) if version else u32(track.media_duration),
        u16(_language_field(flavor, track)),
        u16(0),  # quality
    )
    name = track.name or _HANDLER_NAMES.get(track.kind, "")
    parts = [mdhd, _hdlr(flavor, _HANDLERS[track.kind], name)]
    if track.tag:
        parts.append(full_box("elng", 0, 0, track.tag.encode("ascii") + b"\x00"))
    media_header = {
        "video": full_box("vmhd", 0, 1, bytes(8)),
        "audio": full_box("smhd", 0, 0, bytes(4)),
        "subtitle": full_box("nmhd", 0, 0),
    }[track.kind]
    minf = [media_header]
    if flavor == "mov":
        minf.append(_DATA_HANDLER)
    minf += [_DATA_INFORMATION, _stbl(track, offsets, wide)]
    parts.append(box("minf", *minf))
    return box("mdia", *parts)


def _stbl(track: TrackPlan, offsets: Sequence[int], wide: bool) -> bytes:
    entries = full_box("stsd", 0, 0, u32(len(track.sample_entries)), *track.sample_entries)
    parts = [entries, stts_box(track.durations)]
    parts.extend(extra for extra in (stss_box(track.sync), ctts_box(track.ctos)) if extra)
    parts += [stsc_box(track.chunks), stsz_box(track.sizes), chunk_offsets_box(offsets, wide=wide)]
    return box("stbl", *parts)


def _hdlr(flavor: Flavor, handler: str, name: str) -> bytes:
    text = name.replace("\x00", "").encode("utf-8")
    if flavor == "mov":
        text = text[:255].decode("utf-8", errors="ignore").encode("utf-8")
        return full_box(
            "hdlr", 0, 0, b"mhlr", handler.encode("ascii"), bytes(12), u8(len(text)), text
        )
    return full_box("hdlr", 0, 0, bytes(4), handler.encode("ascii"), bytes(12), text, b"\x00")


def _language_field(flavor: Flavor, track: TrackPlan) -> int:
    if flavor == "mov":
        mac = mac_language_code(track.tag or track.language)
        if mac is not None:
            return mac
    return pack_language(track.language)


def _version(flavor: Flavor, duration: int) -> int:
    if duration < I32_MAX:
        return 0
    if flavor == "mov":
        raise MuxError(
            "The video is too long for a QuickTime .mov file with its time scale.",
            suggestion="Download this video as .mp4 instead of .mov.",
        )
    return 1
