"""Plan a Matroska (``.mkv``) or WebM (``.webm``) file from indexed tracks and subtitles.

Like :mod:`utmax.core.media.mux`, this never reads frame data. It returns a
:class:`~utmax.core.media.mux.MuxPlan` of the headers it makes (:class:`Blob`) and the frames
to copy from the inputs (:class:`CopyOp`), which ``utmax.adapters.files.write_mux_plan``
streams to disk. The file is laid out as::

    EBML header
    Segment
      SeekHead   where Info, Tracks and Cues are
      Info       1 ms timestamps and the duration
      Tracks     one TrackEntry per track; S_TEXT/UTF8 subtitles (Matroska only)
      Cues       one CuePoint per cluster that starts at a video keyframe
      Cluster... a new one at every video keyframe, and at least every 5 seconds

Frames keep their decode order within a track, and the tracks are interleaved by decode time.
The Cues come before the clusters, so a player can seek at once. Every size and position is
known before anything is written, because the numbers that hold positions are 8 bytes wide.
Equal inputs give equal bytes.
"""

from __future__ import annotations

import heapq
from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal

from utmax.core.media import ebml
from utmax.core.media.model import MediaTrack
from utmax.core.media.mux import Blob, CopyOp, MuxPlan
from utmax.core.media.tx3g import (
    default_subtitle_index,
    normalize_cues,
    strip_formatting,
    track_languages,
    track_name,
)
from utmax.errors import MuxError
from utmax.models import Transcript

__all__ = ["DOCTYPES", "DocType", "plan_matroska"]

DocType = Literal["matroska", "webm"]
DOCTYPES: tuple[DocType, ...] = ("matroska", "webm")

_NS_PER_MS = 1_000_000  # the TimestampScale: every timestamp is in milliseconds
_CLUSTER_SPAN = 5000  # ms
_APP = "u-transcript max"
_WEBM_CODECS = frozenset({"V_VP9", "V_AV1", "A_OPUS", "A_VORBIS"})
_MATROSKA_CODECS = _WEBM_CODECS | {"V_MPEG4/ISO/AVC", "A_AAC"}
_KEYFRAME = 0x80
_WIDE = 8  # bytes of the sizes and positions that must be known before the layout is
_INT16 = range(-32768, 32768)
_MAX_TRACKS = 126  # track numbers are written as one-byte vints in block headers


@dataclass(slots=True)
class _Cluster:
    """The blocks of one cluster: ``(ms, track number, frame or cue index)`` in write order."""

    start: int
    blocks: list[tuple[int, int, int]] = field(default_factory=list)
    cue: tuple[int, int] | None = None  # (ms, track number) of the keyframe it starts with


def plan_matroska(
    tracks: Sequence[MediaTrack],
    *,
    doctype: DocType,
    subtitles: Sequence[Transcript] = (),
    default_subtitle: str | None = None,
) -> MuxPlan:
    """Plan one ``doctype`` file from ``tracks`` (in order) and ``subtitles``.

    The first video and the first audio track are the default ones. Every transcript becomes
    an S_TEXT/UTF8 track; ``default_subtitle`` (a language code) picks the default one, else
    the first. Subtitles never run past the end of the media.

    Raises:
        MuxError: no tracks; a codec the file type cannot hold (WebM takes VP9, AV1, Opus and
            Vorbis; Matroska also H.264 and AAC); subtitles in WebM.
        InvalidOption: ``default_subtitle`` names none of ``subtitles``.
    """
    if doctype not in DOCTYPES:
        raise MuxError(f"Unknown Matroska doctype {doctype!r}; use matroska or webm.")
    if not tracks:
        raise MuxError("There is nothing to mux: no input streams were given.")
    allowed = _WEBM_CODECS if doctype == "webm" else _MATROSKA_CODECS
    for track in tracks:
        if track.codec_id not in allowed:
            raise MuxError(
                f"A {track.codec_id} track cannot go into a .{_extension(doctype)} file.",
                suggestion="Download this video as .mkv, which holds every codec utmax takes.",
            )
    if doctype == "webm" and subtitles:
        raise MuxError("WebM files cannot hold subtitle tracks; write sidecar files instead.")
    if len(tracks) + len(subtitles) > _MAX_TRACKS:
        raise MuxError(f"A file holds at most {_MAX_TRACKS} tracks here.")
    shown = default_subtitle_index([t.language_code for t in subtitles], default_subtitle)
    end = max(track.end for track in tracks)
    first = len(tracks) + 1
    texts = [_cues(transcript, _ms(end)) for transcript in subtitles]
    clusters = _clusters(tracks)
    _place(clusters, texts, first=first)
    entries = [
        _media_entry(number, track, default=_is_default(tracks, number - 1))
        for number, track in enumerate(tracks, start=1)
    ]
    entries += [
        _subtitle_entry(first + index, transcript, default=index == shown, doctype=doctype)
        for index, transcript in enumerate(subtitles)
    ]
    return _layout(doctype, tracks, texts, clusters, entries, duration=end / _NS_PER_MS)


def _extension(doctype: DocType) -> str:
    return "webm" if doctype == "webm" else "mkv"


def _ms(nanoseconds: int) -> int:
    return (nanoseconds + _NS_PER_MS // 2) // _NS_PER_MS


def _is_default(tracks: Sequence[MediaTrack], index: int) -> bool:
    """The first track of each kind is the default one."""
    kind = tracks[index].kind
    return all(track.kind != kind for track in tracks[:index])


def _cues(transcript: Transcript, end: int) -> list[tuple[int, int, bytes]]:
    """``(start, stop, UTF-8 text)`` of each cue, cut at ``end`` (ms)."""
    cues: list[tuple[int, int, bytes]] = []
    for cue in normalize_cues(transcript.segments):
        if cue.start >= end:
            break
        cues.append((cue.start, min(cue.end, end), strip_formatting(cue.text).encode("utf-8")))
    return cues


def _frames(tracks: Sequence[MediaTrack]) -> Iterator[tuple[int, int, int]]:
    """``(decode time, track index, frame index)`` of every frame, interleaved by decode time."""

    def frames_of(index: int, track: MediaTrack) -> Iterator[tuple[int, int, int]]:
        for frame, decode in enumerate(track.decode_times):
            yield decode, index, frame

    return heapq.merge(*(frames_of(index, track) for index, track in enumerate(tracks)))


def _clusters(tracks: Sequence[MediaTrack]) -> list[_Cluster]:
    video = next((index for index, track in enumerate(tracks) if track.kind == "video"), None)
    clusters: list[_Cluster] = []
    current: _Cluster | None = None
    for _, index, frame in _frames(tracks):
        track = tracks[index]
        time = _ms(track.times[frame])
        keyframe = index == video and bool(track.keyframes[frame])
        if current is None or keyframe or time - current.start >= _CLUSTER_SPAN:
            current = _Cluster(start=time)
            if keyframe or video is None:  # a place to seek to
                current.cue = (time, index + 1)
            clusters.append(current)
        current.start = min(current.start, time)
        current.blocks.append((time, index + 1, frame))
    return clusters


def _place(
    clusters: list[_Cluster], texts: Sequence[Sequence[tuple[int, int, bytes]]], *, first: int
) -> None:
    """Put every subtitle cue into the last cluster starting no later than the cue, keeping the
    frames' order and moving each cue in front of the first frame shown after it."""
    starts = [cluster.start for cluster in clusters]
    placed: list[list[tuple[int, int, int]]] = [[] for _ in clusters]
    for offset, track_cues in enumerate(texts):
        for index, (start, _, _) in enumerate(track_cues):
            position = max(bisect_right(starts, start) - 1, 0)
            placed[position].append((start, first + offset, index))
    for cluster, blocks in zip(clusters, placed, strict=True):
        if not blocks:
            continue
        blocks.sort()
        merged: list[tuple[int, int, int]] = []
        waiting = iter(blocks)
        block = next(waiting, None)
        for frame in cluster.blocks:
            while block is not None and block[0] <= frame[0]:
                merged.append(block)
                block = next(waiting, None)
            merged.append(frame)
        while block is not None:
            merged.append(block)
            block = next(waiting, None)
        cluster.blocks = merged
        cluster.start = min(cluster.start, blocks[0][0])


def _media_entry(number: int, track: MediaTrack, *, default: bool) -> bytes:
    video = track.kind == "video"
    parts = [
        ebml.uint(ebml.TRACK_NUMBER, number),
        ebml.uint(ebml.TRACK_UID, number),
        ebml.uint(ebml.TRACK_TYPE, 1 if video else 2),
        ebml.uint(ebml.FLAG_DEFAULT, 1 if default else 0),
        ebml.uint(ebml.FLAG_LACING, 0),
    ]
    if track.language:
        parts.append(ebml.string(ebml.LANGUAGE, track.language))
    parts.append(ebml.string(ebml.CODEC_ID, track.codec_id))
    if track.codec_private:
        parts.append(ebml.binary(ebml.CODEC_PRIVATE, track.codec_private))
    if track.codec_delay:
        parts.append(ebml.uint(ebml.CODEC_DELAY, track.codec_delay))
    if track.seek_pre_roll:
        parts.append(ebml.uint(ebml.SEEK_PRE_ROLL, track.seek_pre_roll))
    if video:
        picture = [
            ebml.uint(ebml.PIXEL_WIDTH, track.width),
            ebml.uint(ebml.PIXEL_HEIGHT, track.height),
        ]
        if track.colour:
            picture.append(track.colour)
        parts.append(ebml.element(ebml.VIDEO, *picture))
    else:
        sound = [
            ebml.float64(ebml.SAMPLING_FREQUENCY, track.sampling_frequency),
            ebml.uint(ebml.CHANNELS, track.channels or 2),
        ]
        if track.bit_depth:
            sound.append(ebml.uint(ebml.BIT_DEPTH, track.bit_depth))
        parts.append(ebml.element(ebml.AUDIO, *sound))
    return ebml.element(ebml.TRACK_ENTRY, *parts)


def _subtitle_entry(
    number: int, transcript: Transcript, *, default: bool, doctype: DocType
) -> bytes:
    language, tag = track_languages(transcript.language_code)
    parts = [
        ebml.uint(ebml.TRACK_NUMBER, number),
        ebml.uint(ebml.TRACK_UID, number),
        ebml.uint(ebml.TRACK_TYPE, 0x11),
        ebml.uint(ebml.FLAG_DEFAULT, 1 if default else 0),
        ebml.uint(ebml.FLAG_LACING, 0),
        ebml.string(ebml.LANGUAGE, language),
    ]
    if doctype == "matroska":
        parts.append(ebml.string(ebml.LANGUAGE_BCP47, tag))
    parts.append(ebml.string(ebml.NAME, track_name(transcript)))
    parts.append(ebml.string(ebml.CODEC_ID, "S_TEXT/UTF8"))
    return ebml.element(ebml.TRACK_ENTRY, *parts)


def _cluster_ops(
    cluster: _Cluster,
    tracks: Sequence[MediaTrack],
    texts: Sequence[Sequence[tuple[int, int, bytes]]],
) -> list[CopyOp | Blob]:
    """The payload of one cluster: its timestamp, block headers and the frames to copy."""
    ops: list[CopyOp | Blob] = []
    pending = bytearray(ebml.uint(ebml.TIMESTAMP, cluster.start))
    for time, number, index in cluster.blocks:
        relative = time - cluster.start
        if relative not in _INT16:
            raise MuxError(f"A block lies {relative} ms from its cluster; it cannot be written.")
        header = bytes([0x80 | number]) + relative.to_bytes(2, "big", signed=True)
        if number <= len(tracks):
            track = tracks[number - 1]
            size = track.sizes[index]
            flags = _KEYFRAME if track.keyframes[index] else 0
            pending += ebml.encode_id(ebml.SIMPLE_BLOCK) + ebml.encode_size(4 + size)
            pending += header + bytes([flags])
            ops.append(Blob(bytes(pending)))
            pending.clear()
            if size:
                ops.append(CopyOp(track.source, track.offsets[index], size))
            continue
        start, stop, text = texts[number - len(tracks) - 1][index]
        pending += ebml.element(
            ebml.BLOCK_GROUP,
            ebml.element(ebml.BLOCK, header, b"\x00", text),
            ebml.uint(ebml.BLOCK_DURATION, stop - start),
        )
    if pending:
        ops.append(Blob(bytes(pending)))
    return ops


def _layout(
    doctype: DocType,
    tracks: Sequence[MediaTrack],
    texts: Sequence[Sequence[tuple[int, int, bytes]]],
    clusters: Sequence[_Cluster],
    entries: Sequence[bytes],
    *,
    duration: float,
) -> MuxPlan:
    head = ebml.element(
        ebml.EBML,
        ebml.uint(ebml.EBML_VERSION, 1),
        ebml.uint(ebml.EBML_READ_VERSION, 1),
        ebml.uint(ebml.EBML_MAX_ID_LENGTH, 4),
        ebml.uint(ebml.EBML_MAX_SIZE_LENGTH, 8),
        ebml.string(ebml.DOC_TYPE, doctype),
        ebml.uint(ebml.DOC_TYPE_VERSION, 4),
        ebml.uint(ebml.DOC_TYPE_READ_VERSION, 2),
    )
    info = ebml.element(
        ebml.INFO,
        ebml.uint(ebml.TIMESTAMP_SCALE, _NS_PER_MS),
        ebml.string(ebml.MUXING_APP, _APP),
        ebml.string(ebml.WRITING_APP, _APP),
        ebml.float64(ebml.DURATION, duration),
    )
    track_list = ebml.element(ebml.TRACKS, *entries)
    payloads = [_cluster_ops(cluster, tracks, texts) for cluster in clusters]
    sizes = [sum(_size(op) for op in ops) for ops in payloads]
    points = [cluster.cue for cluster in clusters]
    with_cues = any(point is not None for point in points)
    seek_size = len(_seek_head([0] * (3 if with_cues else 2), with_cues))
    info_at = seek_size
    tracks_at = info_at + len(info)
    cues_at = tracks_at + len(track_list)
    cues_size = len(_cue_list(points, [0] * len(clusters))) if with_cues else 0
    positions: list[int] = []
    position = cues_at + cues_size
    for size in sizes:
        positions.append(position)
        position += 4 + _WIDE + size
    segment = (
        _seek_head([info_at, tracks_at, cues_at] if with_cues else [info_at, tracks_at], with_cues)
        + info
        + track_list
        + (_cue_list(points, positions) if with_cues else b"")
    )
    ops: list[CopyOp | Blob] = [
        Blob(
            head + ebml.encode_id(ebml.SEGMENT) + ebml.encode_size(position, length=_WIDE) + segment
        )
    ]
    for size, payload in zip(sizes, payloads, strict=True):
        _append(ops, Blob(ebml.encode_id(ebml.CLUSTER) + ebml.encode_size(size, length=_WIDE)))
        for op in payload:
            _append(ops, op)
    return MuxPlan(tuple(ops))


def _seek_head(positions: Sequence[int], with_cues: bool) -> bytes:
    targets = [ebml.INFO, ebml.TRACKS, ebml.CUES][: 3 if with_cues else 2]
    return ebml.element(
        ebml.SEEK_HEAD,
        *(
            ebml.element(
                ebml.SEEK,
                ebml.binary(ebml.SEEK_ID, ebml.encode_id(target)),
                ebml.uint(ebml.SEEK_POSITION, position, width=_WIDE),
            )
            for target, position in zip(targets, positions, strict=True)
        ),
    )


def _cue_list(points: Sequence[tuple[int, int] | None], positions: Sequence[int]) -> bytes:
    return ebml.element(
        ebml.CUES,
        *(
            ebml.element(
                ebml.CUE_POINT,
                ebml.uint(ebml.CUE_TIME, point[0], width=_WIDE),
                ebml.element(
                    ebml.CUE_TRACK_POSITIONS,
                    ebml.uint(ebml.CUE_TRACK, point[1]),
                    ebml.uint(ebml.CUE_CLUSTER_POSITION, position, width=_WIDE),
                ),
            )
            for point, position in zip(points, positions, strict=True)
            if point is not None
        ),
        size_length=_WIDE,
    )


def _append(ops: list[CopyOp | Blob], op: CopyOp | Blob) -> None:
    """Add ``op``, joining it to a Blob just before it."""
    if isinstance(op, Blob) and ops and isinstance(ops[-1], Blob):
        ops[-1] = Blob(ops[-1].data + op.data)
    else:
        ops.append(op)


def _size(op: CopyOp | Blob) -> int:
    return op.size if isinstance(op, CopyOp) else len(op.data)
