"""Index WebM (and Matroska) streams, YouTube's VP9 and Opus format, without reading frames.

:func:`index_webm` reads the EBML header, the Segment's ``Info`` and ``Tracks``, and the
header of every block in every ``Cluster``: where each frame's bytes are, when it is shown and
whether it is a keyframe. Frame data is never read. Clusters of unknown size (written live) end
where the next top-level element starts. YouTube writes no lacing, so laced blocks are refused.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass

from utmax.core.media import ebml
from utmax.core.media.boxes import ByteSource, read_exact
from utmax.core.media.ebml import UNKNOWN_SIZE, ElementHeader, children, read_header, read_vint
from utmax.errors import MuxError

__all__ = ["FrameTable", "WebmTrack", "index_webm"]

_KINDS = {1: "video", 2: "audio", 0x11: "subtitle"}
_WINDOW = 1 << 16
_BLOCK_HEADER = 11  # an 8-byte track number, a 16-bit timestamp and the flags
_KEYFRAME = 0x80
_LACING = 0x06
_DEFAULT_SCALE = 1_000_000  # nanoseconds per timestamp tick


class FrameTable:
    """Parallel arrays with one entry per frame, in stream order; times in nanoseconds."""

    __slots__ = ("keyframes", "offsets", "sizes", "times")

    def __init__(self) -> None:
        self.offsets: array[int] = array("q")
        self.sizes: array[int] = array("q")
        self.times: array[int] = array("q")
        self.keyframes = bytearray()

    def __len__(self) -> int:
        return len(self.sizes)


@dataclass(frozen=True, slots=True)
class WebmTrack:
    """One track of a WebM input: what its ``TrackEntry`` says, and every frame."""

    number: int
    kind: str  # "video", "audio", "subtitle" or "other"
    codec_id: str
    codec_private: bytes | None
    codec_delay: int  # nanoseconds
    seek_pre_roll: int  # nanoseconds
    language: str | None
    default_duration: int | None  # nanoseconds
    width: int
    height: int
    colour: bytes | None  # the whole Colour element, as the source wrote it
    sampling_frequency: float
    channels: int
    bit_depth: int | None
    frames: FrameTable


class _Window:
    """Reads through a 64 KiB window, so the many small headers of a stream cost few reads."""

    def __init__(self, source: ByteSource) -> None:
        self._source = source
        self._start = 0
        self._data = b""

    @property
    def size(self) -> int:
        return self._source.size

    def read(self, offset: int, n: int) -> bytes:
        start = offset - self._start
        if start < 0 or start + n > len(self._data):
            self._data = self._source.read(offset, max(n, _WINDOW))
            self._start, start = offset, 0
        return self._data[start : start + n]


def index_webm(source: ByteSource) -> list[WebmTrack]:
    """Every track of a WebM or Matroska input, with its frames, in ``Tracks`` order.

    Raises:
        MuxError: the input is not WebM/Matroska, is truncated or malformed, uses lacing, or
            has a track without frames.
    """
    window = _Window(source)
    try:
        header = read_header(window, 0)
    except MuxError:
        header = None
    if header is None or header.element_id != ebml.EBML or header.size == UNKNOWN_SIZE:
        raise MuxError("The input is not WebM or Matroska: it has no EBML header.")
    doctype = _doctype(read_exact(window, header.payload_offset, header.size))
    if doctype not in ("webm", "matroska"):
        raise MuxError(f"The input is EBML of type {doctype!r}, not WebM or Matroska.")
    segment = read_header(window, header.end)
    if segment.element_id != ebml.SEGMENT:
        raise MuxError("The WebM input has no Segment after its EBML header.")
    end = source.size if segment.size == UNKNOWN_SIZE else min(segment.end, source.size)
    scale = _DEFAULT_SCALE
    entries: list[bytes] = []
    tables: dict[int, FrameTable] = {}
    position = segment.payload_offset
    while position < end:
        child = read_header(window, position)
        if child.element_id == ebml.CLUSTER:
            position = _cluster(window, child, end, tables)
            continue
        if child.size == UNKNOWN_SIZE:
            raise MuxError("A WebM element other than a Cluster has an unknown size.")
        if child.element_id == ebml.INFO:
            scale = _timestamp_scale(read_exact(window, child.payload_offset, child.size))
        elif child.element_id == ebml.TRACKS:
            entries = [
                payload
                for element_id, payload in children(
                    read_exact(window, child.payload_offset, child.size)
                )
                if element_id == ebml.TRACK_ENTRY
            ]
        position = child.end
    if not entries:
        raise MuxError("The WebM input has no Tracks element.")
    tracks = [_track(entry, tables, scale) for entry in entries]
    return [track for track in tracks if track is not None]


def _doctype(payload: bytes) -> str:
    for element_id, value in children(payload):
        if element_id == ebml.DOC_TYPE:
            return value.decode("ascii", errors="replace")
    return "matroska"  # the EBML default


def _timestamp_scale(payload: bytes) -> int:
    for element_id, value in children(payload):
        if element_id == ebml.TIMESTAMP_SCALE:
            scale = ebml.uint_value(value)
            if scale <= 0:
                raise MuxError("The WebM input has a timestamp scale of 0.")
            return scale
    return _DEFAULT_SCALE


def _cluster(
    window: _Window, cluster: ElementHeader, segment_end: int, tables: dict[int, FrameTable]
) -> int:
    """Index the blocks of ``cluster``; return where the next element starts."""
    unknown = cluster.size == UNKNOWN_SIZE
    end = segment_end if unknown else min(cluster.end, segment_end)
    base: int | None = None
    position = cluster.payload_offset
    while position < end:
        child = read_header(window, position)
        if unknown and child.element_id in ebml.TOP_LEVEL:
            return position
        if child.size == UNKNOWN_SIZE:
            raise MuxError("A WebM block has an unknown size.")
        if child.element_id == ebml.TIMESTAMP:
            base = ebml.uint_value(read_exact(window, child.payload_offset, child.size))
        elif child.element_id == ebml.SIMPLE_BLOCK:
            _block(window, child, base, tables, keyframe=None)
        elif child.element_id == ebml.BLOCK_GROUP:
            _group(window, child, base, tables)
        position = child.end
    return end


def _group(
    window: _Window, group: ElementHeader, base: int | None, tables: dict[int, FrameTable]
) -> None:
    block: ElementHeader | None = None
    referenced = False
    position = group.payload_offset
    while position < group.end:
        child = read_header(window, position)
        if child.size == UNKNOWN_SIZE:
            raise MuxError("A WebM block group holds an element of unknown size.")
        if child.element_id == ebml.BLOCK:
            block = child
        elif child.element_id == ebml.REFERENCE_BLOCK:
            referenced = True
        position = child.end
    if block is not None:
        _block(window, block, base, tables, keyframe=not referenced)


def _block(
    window: _Window,
    block: ElementHeader,
    base: int | None,
    tables: dict[int, FrameTable],
    *,
    keyframe: bool | None,
) -> None:
    """Record one frame; ``keyframe`` is ``None`` for a SimpleBlock, whose flags say it."""
    if base is None:
        raise MuxError("A WebM cluster has a block before its timestamp.")
    data = window.read(block.payload_offset, min(_BLOCK_HEADER, block.size))
    track, length = read_vint(data, 0)
    if len(data) < length + 3:
        raise MuxError("A WebM block is shorter than its header.")
    flags = data[length + 2]
    if flags & _LACING:
        raise MuxError("The WebM input uses laced blocks, which utmax cannot split.")
    relative = int.from_bytes(data[length : length + 2], "big", signed=True)
    table = tables.setdefault(track, FrameTable())
    table.offsets.append(block.payload_offset + length + 3)
    table.sizes.append(block.size - length - 3)
    table.times.append(base + relative)
    table.keyframes.append(1 if (bool(flags & _KEYFRAME) if keyframe is None else keyframe) else 0)


def _track(entry: bytes, tables: dict[int, FrameTable], scale: int) -> WebmTrack | None:
    """The track of one ``TrackEntry``; ``None`` for a subtitle or other track without frames."""
    fields = dict(children(entry))
    number = ebml.uint_value(fields.get(ebml.TRACK_NUMBER, b""))
    codec = fields.get(ebml.CODEC_ID, b"").decode("ascii", errors="replace")
    kind = _KINDS.get(ebml.uint_value(fields.get(ebml.TRACK_TYPE, b"")), "other")
    frames = tables.get(number)
    if frames is None or not len(frames):
        if kind in ("video", "audio"):
            raise MuxError(f"WebM track {number} ({codec or 'no codec'}) has no frames.")
        return None
    frames.times = array("q", (tick * scale for tick in frames.times))
    video = dict(children(fields.get(ebml.VIDEO, b"")))
    audio = dict(children(fields.get(ebml.AUDIO, b"")))
    colour = video.get(ebml.COLOUR)
    language = fields.get(ebml.LANGUAGE)
    duration = fields.get(ebml.DEFAULT_DURATION)
    depth = audio.get(ebml.BIT_DEPTH)
    return WebmTrack(
        number=number,
        kind=kind,
        codec_id=codec,
        codec_private=fields.get(ebml.CODEC_PRIVATE),
        codec_delay=ebml.uint_value(fields.get(ebml.CODEC_DELAY, b"")),
        seek_pre_roll=ebml.uint_value(fields.get(ebml.SEEK_PRE_ROLL, b"")),
        language=None if language is None else language.decode("ascii", errors="replace"),
        default_duration=None if duration is None else ebml.uint_value(duration),
        width=ebml.uint_value(video.get(ebml.PIXEL_WIDTH, b"")),
        height=ebml.uint_value(video.get(ebml.PIXEL_HEIGHT, b"")),
        colour=None if colour is None else ebml.element(ebml.COLOUR, colour),
        sampling_frequency=ebml.float_value(audio.get(ebml.SAMPLING_FREQUENCY, b"")) or 8000.0,
        channels=ebml.uint_value(audio.get(ebml.CHANNELS, b"\x01")),
        bit_depth=None if depth is None else ebml.uint_value(depth),
        frames=frames,
    )
