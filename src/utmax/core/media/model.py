"""The shared media model: what the Matroska writer needs of a track, whatever its source.

:func:`media_tracks` indexes one input, fragmented MP4 (H.264, AV1, AAC) or WebM (VP9, AV1,
Opus), into :class:`MediaTrack`: where every frame's bytes are, when it is shown and decoded
(nanoseconds on the presentation timeline), whether it is a keyframe, and how a Matroska
``TrackEntry`` describes it.

MP4 times follow the track's edit list the way an MP4 player shows them: a frame's
presentation time is ``dts + cto - media_time`` (``media_time`` of the first edit) plus any
leading empty edit. Audio frames that end before the timeline starts (encoder priming the edit
list hides) are dropped; a frame that starts before it is moved to 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from utmax.core.media.boxes import ByteSource
from utmax.core.media.codecs import mp4_codec
from utmax.core.media.fmp4 import Edit, IndexedTrack, index_fragments
from utmax.core.media.moov import unpack_language
from utmax.core.media.webm import WebmTrack, index_webm
from utmax.errors import MuxError

__all__ = ["MediaTrack", "from_fmp4", "from_webm", "media_tracks"]

_NS = 1_000_000_000


@dataclass(frozen=True, slots=True)
class MediaTrack:
    """One video or audio track of input number ``source``, frames in decode order."""

    source: int
    kind: Literal["video", "audio"]
    codec_id: str  # the Matroska CodecID, such as "V_VP9" or "A_OPUS"
    codec_private: bytes | None
    offsets: Sequence[int]
    sizes: Sequence[int]
    times: Sequence[int]  # presentation times, nanoseconds
    decode_times: Sequence[int]  # nanoseconds
    keyframes: bytes
    end: int  # when the last frame ends, nanoseconds
    width: int = 0
    height: int = 0
    colour: bytes | None = None  # a Matroska Colour element
    sampling_frequency: float = 0.0
    channels: int = 0
    bit_depth: int | None = None
    codec_delay: int = 0  # nanoseconds
    seek_pre_roll: int = 0  # nanoseconds
    language: str | None = None  # ISO 639-2

    def __post_init__(self) -> None:
        if not self.sizes:
            raise MuxError(f"A {self.kind} track ({self.codec_id}) has no frames.")


def media_tracks(source: ByteSource, number: int, *, container: str) -> list[MediaTrack]:
    """The video and audio tracks of input ``number``: WebM when ``container`` is
    ``"webm"``, fragmented MP4 otherwise.

    Raises:
        MuxError: the input is malformed or holds a codec Matroska cannot take from it.
    """
    if container == "webm":
        return [
            from_webm(number, track)
            for track in index_webm(source)
            if track.kind in ("video", "audio")
        ]
    return [from_fmp4(number, track) for track in index_fragments(source)]


def from_fmp4(source: int, track: IndexedTrack) -> MediaTrack:
    """A fragmented MP4 track as a :class:`MediaTrack` (see the module docs for the timing)."""
    header, samples = track.header, track.samples
    config = mp4_codec(header.sample_entries[0])
    scale = header.timescale
    media_time = next((edit.media_time for edit in header.edits if edit.media_time >= 0), 0)
    lead = _ns(_leading_empty(header.edits), header.movie_timescale or 1)
    times: list[int] = []
    decode: list[int] = []
    keep: list[int] = []
    end = 0
    for index, (dts, cto, duration) in enumerate(
        zip(samples.dts, samples.ctos, samples.durations, strict=True)
    ):
        shown = _ns(dts + cto - media_time, scale) + lead
        finish = _ns(dts + cto + duration - media_time, scale) + lead
        if config.kind == "audio" and finish <= 0:
            continue  # priming the edit list hides
        times.append(max(shown, 0))
        decode.append(_ns(dts - media_time, scale) + lead)
        keep.append(index)
        end = max(end, finish)
    return MediaTrack(
        source=source,
        kind=config.kind,
        codec_id=config.codec_id,
        codec_private=config.codec_private,
        offsets=[samples.offsets[index] for index in keep],
        sizes=[samples.sizes[index] for index in keep],
        times=times,
        decode_times=decode,
        keyframes=bytes(samples.sync[index] for index in keep),
        end=end,
        width=config.width,
        height=config.height,
        colour=config.colour,
        sampling_frequency=config.sampling_frequency,
        channels=config.channels,
        language=unpack_language(header.language),
    )


def from_webm(source: int, track: WebmTrack) -> MediaTrack:
    """A WebM track as a :class:`MediaTrack`; WebM times are presentation times already."""
    if track.kind not in ("video", "audio"):
        raise MuxError(f"WebM track {track.number} holds {track.kind} data, not video or audio.")
    frames = track.frames
    times = list(frames.times)
    latest = max(times)
    last = times[-1] + (track.default_duration or _typical_step(times))
    return MediaTrack(
        source=source,
        kind="video" if track.kind == "video" else "audio",
        codec_id=track.codec_id,
        codec_private=track.codec_private,
        offsets=list(frames.offsets),
        sizes=list(frames.sizes),
        times=times,
        decode_times=times,
        keyframes=bytes(frames.keyframes),
        end=max(last, latest),
        width=track.width,
        height=track.height,
        colour=track.colour,
        sampling_frequency=track.sampling_frequency,
        channels=track.channels,
        bit_depth=track.bit_depth,
        codec_delay=track.codec_delay,
        seek_pre_roll=track.seek_pre_roll,
        language=track.language,
    )


def _leading_empty(edits: Sequence[Edit]) -> int:
    """How long the empty edits before the first media edit last, in movie ticks."""
    total = 0
    for edit in edits:
        if edit.media_time >= 0:
            break
        total += edit.duration
    return total


def _ns(ticks: int, scale: int) -> int:
    """``ticks`` of a ``scale`` Hz clock in nanoseconds, rounded half up."""
    return (2 * ticks * _NS + scale) // (2 * scale)


def _typical_step(times: Sequence[int]) -> int:
    """The usual gap between frames, for the duration of the last one."""
    steps = sorted(b - a for a, b in zip(times[-9:], times[-8:], strict=False) if b > a)
    return steps[len(steps) // 2] if steps else 0
