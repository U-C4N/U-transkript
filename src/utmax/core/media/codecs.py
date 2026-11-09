"""Codec configuration for Matroska, from the MP4 sample descriptions of YouTube's streams.

Matroska keeps the decoder configuration MP4 keeps, only elsewhere:

- H.264 (``avc1``): ``V_MPEG4/ISO/AVC`` with the ``avcC`` payload as CodecPrivate.
- AV1 (``av01``): ``V_AV1`` with the ``av1C`` payload as CodecPrivate.
- AAC (``mp4a``): ``A_AAC`` with the AudioSpecificConfig inside ``esds`` as CodecPrivate.

The ``colr`` (nclx), ``mdcv`` and ``clli`` boxes of a video become a ``Colour`` element, so HDR
survives the change of container.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from utmax.core.media import ebml
from utmax.core.media.boxes import child_boxes
from utmax.errors import MuxError

__all__ = ["CodecConfig", "audio_specific_config", "mp4_codec"]

_VISUAL_FIELDS = 78  # VisualSampleEntry fields before its child boxes
_AUDIO_FIELDS = {0: 28, 1: 44, 2: 64}  # AudioSampleEntry fields by QuickTime sound version
_AAC_RATES = (
    96000,
    88200,
    64000,
    48000,
    44100,
    32000,
    24000,
    22050,
    16000,
    12000,
    11025,
    8000,
    7350,
)


@dataclass(frozen=True, slots=True)
class CodecConfig:
    """How one MP4 track is described in Matroska."""

    kind: Literal["video", "audio"]
    codec_id: str
    codec_private: bytes
    width: int = 0
    height: int = 0
    colour: bytes | None = None
    sampling_frequency: float = 0.0
    channels: int = 0


def mp4_codec(entry: bytes) -> CodecConfig:
    """The Matroska description of an ``avc1``, ``av01`` or ``mp4a`` sample entry.

    Raises:
        MuxError: another codec, or a sample entry without its configuration box.
    """
    kind = entry[4:8].decode("latin-1")
    if kind in ("avc1", "av01"):
        if len(entry) < 8 + _VISUAL_FIELDS:
            raise MuxError(f"The {kind!r} sample description is truncated.")
        boxes = dict(child_boxes(entry[8 + _VISUAL_FIELDS :], context=kind))
        name = "avcC" if kind == "avc1" else "av1C"
        config = boxes.get(name)
        if config is None:
            raise MuxError(f"The {kind!r} sample description has no {name!r} box.")
        return CodecConfig(
            kind="video",
            codec_id="V_MPEG4/ISO/AVC" if kind == "avc1" else "V_AV1",
            codec_private=config,
            width=int.from_bytes(entry[32:34], "big"),
            height=int.from_bytes(entry[34:36], "big"),
            colour=colour_element(boxes),
        )
    if kind == "mp4a":
        version = int.from_bytes(entry[16:18], "big")
        fields = _AUDIO_FIELDS.get(version, _AUDIO_FIELDS[0])
        boxes = dict(child_boxes(entry[8 + fields :], context=kind))
        esds = boxes.get("esds")
        if esds is None:
            raise MuxError("The 'mp4a' sample description has no 'esds' box.")
        config = audio_specific_config(esds)
        rate = int.from_bytes(entry[32:36], "big") >> 16 if version < 2 else 0
        return CodecConfig(
            kind="audio",
            codec_id="A_AAC",
            codec_private=config,
            sampling_frequency=float(rate or _aac_rate(config)),
            channels=int.from_bytes(entry[24:26], "big"),
        )
    raise MuxError(
        f"A {kind!r} track cannot go into Matroska; only H.264, AV1 and AAC tracks of MP4 can."
    )


def audio_specific_config(esds: bytes) -> bytes:
    """The AudioSpecificConfig inside an ``esds`` payload (ISO/IEC 14496-1 descriptors).

    Raises:
        MuxError: the descriptors are not ES > DecoderConfig > DecoderSpecificInfo.
    """
    data = esds[4:]  # version and flags
    tag, _, position = _descriptor(data, 0)
    if tag != 0x03:
        raise MuxError("The 'esds' box does not start with an ES descriptor.")
    flags = data[position + 2] if position + 2 < len(data) else 0
    position += 3
    if flags & 0x80:  # streamDependenceFlag
        position += 2
    if flags & 0x40:  # URL_Flag
        position += 1 + (data[position] if position < len(data) else 0)
    if flags & 0x20:  # OCRstreamFlag
        position += 2
    tag, _, position = _descriptor(data, position)
    if tag != 0x04:
        raise MuxError("The 'esds' box has no decoder configuration.")
    tag, size, position = _descriptor(data, position + 13)
    if tag != 0x05 or position + size > len(data):
        raise MuxError("The 'esds' box has no decoder-specific information.")
    return data[position : position + size]


def colour_element(boxes: Mapping[str, bytes]) -> bytes | None:
    """A Matroska ``Colour`` element from a video's ``colr``, ``clli`` and ``mdcv`` boxes."""
    parts: list[bytes] = []
    colr = boxes.get("colr")
    if colr is not None and colr[:4] in (b"nclx", b"nclc") and len(colr) >= 10:
        primaries, transfer, matrix = struct.unpack(">HHH", colr[4:10])
        parts.append(ebml.uint(ebml.MATRIX_COEFFICIENTS, matrix))
        if colr[:4] == b"nclx" and len(colr) >= 11:
            parts.append(ebml.uint(ebml.RANGE, 2 if colr[10] & 0x80 else 1))
        parts.append(ebml.uint(ebml.TRANSFER_CHARACTERISTICS, transfer))
        parts.append(ebml.uint(ebml.PRIMARIES, primaries))
    clli = boxes.get("clli")
    if clli is not None and len(clli) >= 4:
        max_cll, max_fall = struct.unpack(">HH", clli[:4])
        parts.append(ebml.uint(ebml.MAX_CLL, max_cll))
        parts.append(ebml.uint(ebml.MAX_FALL, max_fall))
    mdcv = boxes.get("mdcv")
    if mdcv is not None and len(mdcv) >= 24:
        # Green, blue, red, then the white point (units of 0.00002), then luminance (0.0001).
        gx, gy, bx, by, rx, ry, wx, wy, high, low = struct.unpack(">8H2I", mdcv[:24])
        chroma = (
            (ebml.PRIMARY_R_X, rx),
            (ebml.PRIMARY_R_Y, ry),
            (ebml.PRIMARY_G_X, gx),
            (ebml.PRIMARY_G_Y, gy),
            (ebml.PRIMARY_B_X, bx),
            (ebml.PRIMARY_B_Y, by),
            (ebml.WHITE_POINT_X, wx),
            (ebml.WHITE_POINT_Y, wy),
        )
        parts.append(
            ebml.element(
                ebml.MASTERING_METADATA,
                *(ebml.float64(element_id, value / 50000) for element_id, value in chroma),
                ebml.float64(ebml.LUMINANCE_MAX, high / 10000),
                ebml.float64(ebml.LUMINANCE_MIN, low / 10000),
            )
        )
    return ebml.element(ebml.COLOUR, *parts) if parts else None


def _descriptor(data: bytes, position: int) -> tuple[int, int, int]:
    """``(tag, size, payload start)`` of the MPEG-4 descriptor at ``position``."""
    if position >= len(data):
        raise MuxError("The 'esds' box is truncated.")
    tag = data[position]
    position += 1
    size = 0
    for _ in range(4):
        if position >= len(data):
            raise MuxError("The 'esds' box is truncated.")
        byte = data[position]
        position += 1
        size = (size << 7) | (byte & 0x7F)
        if not byte & 0x80:
            break
    return tag, size, position


def _aac_rate(config: bytes) -> int:
    """The sampling rate an AudioSpecificConfig gives (44100 when it cannot be read)."""
    if len(config) < 2:
        return 44100
    bits = int.from_bytes(config[:5].ljust(5, b"\0"), "big")
    shift = 40 - 5
    if (bits >> shift) & 0x1F == 31:  # escaped object type
        shift -= 6
    index = (bits >> (shift - 4)) & 0x0F
    if index < len(_AAC_RATES):
        return _AAC_RATES[index]
    return (bits >> (shift - 28)) & 0xFFFFFF if index == 15 else 44100
