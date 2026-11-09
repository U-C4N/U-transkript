"""EBML, the binary format under Matroska and WebM: element IDs, sizes and values.

An element is its ID (1-4 bytes, length marker included), its payload size as a variable
length integer (a "vint": the count of leading zero bits says how many more bytes follow) and
its payload. A size with every value bit set means "unknown" (streams written live).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from utmax.core.media.boxes import ByteSource
from utmax.errors import MuxError

__all__ = [
    "UNKNOWN_SIZE",
    "ElementHeader",
    "binary",
    "children",
    "element",
    "encode_id",
    "encode_size",
    "float64",
    "float_value",
    "read_header",
    "read_id",
    "read_vint",
    "string",
    "uint",
    "uint_value",
]

UNKNOWN_SIZE = -1
_MAX_HEADER = 12  # a 4-byte ID and an 8-byte size

# Element IDs (Matroska specification, RFC 9559), marker bits included.
EBML = 0x1A45DFA3
EBML_VERSION = 0x4286
EBML_READ_VERSION = 0x42F7
EBML_MAX_ID_LENGTH = 0x42F2
EBML_MAX_SIZE_LENGTH = 0x42F3
DOC_TYPE = 0x4282
DOC_TYPE_VERSION = 0x4287
DOC_TYPE_READ_VERSION = 0x4285
VOID = 0xEC
SEGMENT = 0x18538067
SEEK_HEAD = 0x114D9B74
SEEK = 0x4DBB
SEEK_ID = 0x53AB
SEEK_POSITION = 0x53AC
INFO = 0x1549A966
TIMESTAMP_SCALE = 0x2AD7B1
DURATION = 0x4489
MUXING_APP = 0x4D80
WRITING_APP = 0x5741
TRACKS = 0x1654AE6B
TRACK_ENTRY = 0xAE
TRACK_NUMBER = 0xD7
TRACK_UID = 0x73C5
TRACK_TYPE = 0x83
FLAG_DEFAULT = 0x88
FLAG_LACING = 0x9C
LANGUAGE = 0x22B59C
LANGUAGE_BCP47 = 0x22B59D
NAME = 0x536E
CODEC_ID = 0x86
CODEC_PRIVATE = 0x63A2
CODEC_DELAY = 0x56AA
SEEK_PRE_ROLL = 0x56BB
DEFAULT_DURATION = 0x23E383
VIDEO = 0xE0
PIXEL_WIDTH = 0xB0
PIXEL_HEIGHT = 0xBA
COLOUR = 0x55B0
MATRIX_COEFFICIENTS = 0x55B1
RANGE = 0x55B9
TRANSFER_CHARACTERISTICS = 0x55BA
PRIMARIES = 0x55BB
MAX_CLL = 0x55BC
MAX_FALL = 0x55BD
MASTERING_METADATA = 0x55D0
PRIMARY_R_X = 0x55D1
PRIMARY_R_Y = 0x55D2
PRIMARY_G_X = 0x55D3
PRIMARY_G_Y = 0x55D4
PRIMARY_B_X = 0x55D5
PRIMARY_B_Y = 0x55D6
WHITE_POINT_X = 0x55D7
WHITE_POINT_Y = 0x55D8
LUMINANCE_MAX = 0x55D9
LUMINANCE_MIN = 0x55DA
AUDIO = 0xE1
SAMPLING_FREQUENCY = 0xB5
CHANNELS = 0x9F
BIT_DEPTH = 0x6264
CLUSTER = 0x1F43B675
TIMESTAMP = 0xE7
SIMPLE_BLOCK = 0xA3
BLOCK_GROUP = 0xA0
BLOCK = 0xA1
BLOCK_DURATION = 0x9B
REFERENCE_BLOCK = 0xFB
CUES = 0x1C53BB6B
CUE_POINT = 0xBB
CUE_TIME = 0xB3
CUE_TRACK_POSITIONS = 0xB7
CUE_TRACK = 0xF7
CUE_CLUSTER_POSITION = 0xF1
# The elements that follow one another inside a Segment.
TOP_LEVEL = frozenset({SEEK_HEAD, INFO, TRACKS, CLUSTER, CUES, 0x1043A770, 0x1941A469, 0x1254C367})


def encode_id(element_id: int) -> bytes:
    """The bytes of an element ID; IDs carry their own length marker."""
    return element_id.to_bytes(max(1, (element_id.bit_length() + 7) // 8), "big")


def encode_size(size: int, *, length: int | None = None) -> bytes:
    """``size`` as a vint, as short as possible or exactly ``length`` bytes (1-8)."""
    if length is None:
        length = 1
        while size > (1 << (7 * length)) - 2:
            length += 1
    if not 1 <= length <= 8 or size > (1 << (7 * length)) - 2 or size < 0:
        raise MuxError(f"An EBML size of {size} does not fit {length} bytes.")
    return ((1 << (7 * length)) | size).to_bytes(length, "big")


def element(element_id: int, *parts: bytes, size_length: int | None = None) -> bytes:
    """An element with the concatenated ``parts`` as payload."""
    payload = b"".join(parts)
    return encode_id(element_id) + encode_size(len(payload), length=size_length) + payload


def uint(element_id: int, value: int, *, width: int | None = None) -> bytes:
    """An unsigned integer element, in as few bytes as possible or exactly ``width``."""
    size = width if width is not None else max(1, (value.bit_length() + 7) // 8)
    return element(element_id, value.to_bytes(size, "big"))


def float64(element_id: int, value: float) -> bytes:
    """A float element as an 8-byte IEEE double."""
    return element(element_id, struct.pack(">d", value))


def string(element_id: int, text: str) -> bytes:
    """A string element (ASCII or UTF-8)."""
    return element(element_id, text.encode("utf-8"))


def binary(element_id: int, data: bytes) -> bytes:
    """A binary element."""
    return element(element_id, data)


def read_vint(data: bytes, position: int) -> tuple[int, int]:
    """The vint at ``position`` of ``data``: ``(value, length)``; an all-ones value is
    :data:`UNKNOWN_SIZE`.

    Raises:
        MuxError: the vint is longer than 8 bytes or runs past ``data``.
    """
    if position >= len(data):
        raise MuxError("An EBML number runs past the end of the data.")
    first = data[position]
    if first == 0:
        raise MuxError("An EBML number is longer than 8 bytes.")
    length = 9 - first.bit_length()
    if position + length > len(data):
        raise MuxError("An EBML number runs past the end of the data.")
    value = int.from_bytes(data[position : position + length], "big") & ((1 << (7 * length)) - 1)
    return (UNKNOWN_SIZE if value == (1 << (7 * length)) - 1 else value), length


def read_id(data: bytes, position: int) -> tuple[int, int]:
    """The element ID at ``position`` of ``data``: ``(id, length)``, marker bits kept."""
    if position >= len(data) or data[position] == 0:
        raise MuxError("An EBML element ID is malformed.")
    length = 9 - data[position].bit_length()
    if length > 4 or position + length > len(data):
        raise MuxError("An EBML element ID is malformed.")
    return int.from_bytes(data[position : position + length], "big"), length


def uint_value(payload: bytes) -> int:
    """The value of an unsigned integer element's payload."""
    return int.from_bytes(payload, "big")


def float_value(payload: bytes) -> float:
    """The value of a float element's payload (4 or 8 bytes)."""
    if len(payload) == 4:
        return float(struct.unpack(">f", payload)[0])
    if len(payload) == 8:
        return float(struct.unpack(">d", payload)[0])
    if not payload:
        return 0.0
    raise MuxError(f"An EBML float has {len(payload)} bytes; only 4 or 8 are valid.")


@dataclass(frozen=True, slots=True)
class ElementHeader:
    """Where one element sits: its ID, first byte, header size and payload size."""

    element_id: int
    offset: int
    header_size: int
    size: int  # UNKNOWN_SIZE for elements written live

    @property
    def payload_offset(self) -> int:
        return self.offset + self.header_size

    @property
    def end(self) -> int:
        """The first byte after the element (only for a known size)."""
        return self.payload_offset + self.size


def read_header(source: ByteSource, offset: int) -> ElementHeader:
    """The header of the element starting at ``offset`` of ``source``.

    Raises:
        MuxError: the header is malformed or cut off.
    """
    data = source.read(offset, _MAX_HEADER)
    element_id, id_length = read_id(data, 0)
    size, size_length = read_vint(data, id_length)
    return ElementHeader(element_id, offset, id_length + size_length, size)


def children(payload: bytes) -> list[tuple[int, bytes]]:
    """The elements laid end to end in ``payload``, as ``(id, payload)``.

    Raises:
        MuxError: an element is malformed, of unknown size or runs past ``payload``.
    """
    found: list[tuple[int, bytes]] = []
    position = 0
    while position < len(payload):
        element_id, id_length = read_id(payload, position)
        size, size_length = read_vint(payload, position + id_length)
        start = position + id_length + size_length
        if size == UNKNOWN_SIZE or start + size > len(payload):
            raise MuxError("An EBML element runs past the element that holds it.")
        found.append((element_id, payload[start : start + size]))
        position = start + size
    return found
