"""Build small WebM (or Matroska) files for tests: an EBML header, Info, Tracks and Clusters.

Every frame is filled with a pattern unique to (track number, frame number), so the offsets and
sizes a parser reports can be checked byte for byte with :func:`frame_bytes`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from utmax.core.media import ebml

UNKNOWN = b"\x01\xff\xff\xff\xff\xff\xff\xff"  # an 8-byte vint of unknown size
OPUS_HEAD = (
    b"OpusHead"
    + bytes([1, 2])
    + (312).to_bytes(2, "little")
    + (48000).to_bytes(4, "little")
    + bytes(3)
)


@dataclass(frozen=True)
class Frame:
    """One frame: its timestamp (in ticks of the file's scale), size and kind of block."""

    time: int
    size: int
    keyframe: bool = True
    group: bool = False  # a BlockGroup, whose keyframes are the ones without a ReferenceBlock


@dataclass(frozen=True)
class TrackSpec:
    """One TrackEntry."""

    number: int = 1
    kind: int = 1  # 1 video, 2 audio, 0x11 subtitles
    codec: str = "V_VP9"
    private: bytes | None = None
    width: int = 640
    height: int = 360
    rate: float = 48000.0
    channels: int = 2
    codec_delay: int = 0
    seek_pre_roll: int = 0
    language: str | None = "eng"
    colour: bytes | None = None  # a whole Colour element
    default_duration: int | None = None


def frame_bytes(track: int, index: int, size: int) -> bytes:
    """The bytes of frame ``index`` of track ``track``."""
    unit = bytes([0xF0 | (track & 0x0F), (index >> 8) & 0xFF, index & 0xFF, 0xA5])
    return (unit * (size // 4 + 1))[:size]


def webm_file(
    tracks: Sequence[tuple[TrackSpec, Sequence[Frame]]],
    *,
    doctype: str = "webm",
    scale: int = 1_000_000,
    cluster_span: int = 1000,
    unknown_clusters: bool = False,
    unknown_segment: bool = False,
    trailer: bytes = b"",
) -> bytes:
    """A whole file: frames are interleaved by time into clusters of ``cluster_span`` ticks."""
    header = ebml.element(
        ebml.EBML,
        ebml.uint(ebml.EBML_VERSION, 1),
        ebml.uint(ebml.EBML_READ_VERSION, 1),
        ebml.uint(ebml.EBML_MAX_ID_LENGTH, 4),
        ebml.uint(ebml.EBML_MAX_SIZE_LENGTH, 8),
        ebml.string(ebml.DOC_TYPE, doctype),
        ebml.uint(ebml.DOC_TYPE_VERSION, 4),
        ebml.uint(ebml.DOC_TYPE_READ_VERSION, 2),
    )
    info = ebml.element(ebml.INFO, ebml.uint(ebml.TIMESTAMP_SCALE, scale))
    entries = ebml.element(ebml.TRACKS, *(_entry(spec) for spec, _ in tracks))
    timed = sorted(
        (frame.time, spec.number, index, frame)
        for spec, frames in tracks
        for index, frame in enumerate(frames)
    )
    clusters = b""
    position = 0
    while position < len(timed):
        start = timed[position][0]
        blocks = b""
        while position < len(timed) and timed[position][0] < start + cluster_span:
            time, number, index, frame = timed[position]
            blocks += _block(number, index, frame, time - start)
            position += 1
        payload = ebml.uint(ebml.TIMESTAMP, start) + blocks
        size = UNKNOWN if unknown_clusters else ebml.encode_size(len(payload))
        clusters += ebml.encode_id(ebml.CLUSTER) + size + payload
    body = info + entries + ebml.element(ebml.VOID, bytes(3)) + clusters + trailer
    size = UNKNOWN if unknown_segment else ebml.encode_size(len(body))
    return header + ebml.encode_id(ebml.SEGMENT) + size + body


def _entry(spec: TrackSpec) -> bytes:
    parts = [
        ebml.uint(ebml.TRACK_NUMBER, spec.number),
        ebml.uint(ebml.TRACK_UID, 1000 + spec.number),
        ebml.uint(ebml.TRACK_TYPE, spec.kind),
        ebml.string(ebml.CODEC_ID, spec.codec),
    ]
    if spec.language is not None:
        parts.append(ebml.string(ebml.LANGUAGE, spec.language))
    if spec.private is not None:
        parts.append(ebml.binary(ebml.CODEC_PRIVATE, spec.private))
    if spec.codec_delay:
        parts.append(ebml.uint(ebml.CODEC_DELAY, spec.codec_delay))
    if spec.seek_pre_roll:
        parts.append(ebml.uint(ebml.SEEK_PRE_ROLL, spec.seek_pre_roll))
    if spec.default_duration is not None:
        parts.append(ebml.uint(ebml.DEFAULT_DURATION, spec.default_duration))
    if spec.kind == 1:
        picture = [
            ebml.uint(ebml.PIXEL_WIDTH, spec.width),
            ebml.uint(ebml.PIXEL_HEIGHT, spec.height),
        ]
        if spec.colour is not None:
            picture.append(spec.colour)
        parts.append(ebml.element(ebml.VIDEO, *picture))
    elif spec.kind == 2:
        parts.append(
            ebml.element(
                ebml.AUDIO,
                ebml.float64(ebml.SAMPLING_FREQUENCY, spec.rate),
                ebml.uint(ebml.CHANNELS, spec.channels),
            )
        )
    return ebml.element(ebml.TRACK_ENTRY, *parts)


def _block(number: int, index: int, frame: Frame, relative: int) -> bytes:
    data = frame_bytes(number, index, frame.size)
    head = bytes([0x80 | number]) + relative.to_bytes(2, "big", signed=True)
    if not frame.group:
        flags = 0x80 if frame.keyframe else 0x00
        return ebml.element(ebml.SIMPLE_BLOCK, head, bytes([flags]), data)
    parts = [ebml.element(ebml.BLOCK, head, b"\x00", data)]
    if not frame.keyframe:
        parts.append(ebml.element(ebml.REFERENCE_BLOCK, b"\xd8"))  # -40: the frame before
    parts.append(ebml.uint(ebml.BLOCK_DURATION, 40))
    return ebml.element(ebml.BLOCK_GROUP, *parts)
