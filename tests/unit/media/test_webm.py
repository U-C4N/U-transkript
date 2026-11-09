"""Tests for the WebM indexer (synthetic files from tests.helpers.webm_factory)."""

from __future__ import annotations

import pytest

from tests.helpers.webm_factory import OPUS_HEAD, Frame, TrackSpec, frame_bytes, webm_file
from utmax.core.media import ebml
from utmax.core.media.boxes import BytesSource
from utmax.core.media.webm import WebmTrack, index_webm
from utmax.errors import MuxError

VIDEO = TrackSpec(number=1, width=3840, height=2160)
AUDIO = TrackSpec(
    number=2,
    kind=2,
    codec="A_OPUS",
    private=OPUS_HEAD,
    codec_delay=6_500_000,
    seek_pre_roll=80_000_000,
    language=None,
)


def frames_of(data: bytes, track: WebmTrack) -> list[bytes]:
    return [data[o : o + s] for o, s in zip(track.frames.offsets, track.frames.sizes, strict=True)]


def test_tracks_and_frames_are_indexed() -> None:
    video = [Frame(index * 40, 50 + index, keyframe=index % 5 == 0) for index in range(12)]
    audio = [Frame(index * 20, 30 + index) for index in range(24)]
    data = webm_file([(VIDEO, video), (AUDIO, audio)], cluster_span=200)

    first, second = index_webm(BytesSource(data))

    assert (first.number, first.kind, first.codec_id) == (1, "video", "V_VP9")
    assert (first.width, first.height, first.language, first.codec_private) == (
        3840,
        2160,
        "eng",
        None,
    )
    assert frames_of(data, first) == [frame_bytes(1, i, f.size) for i, f in enumerate(video)]
    assert list(first.frames.times) == [index * 40_000_000 for index in range(12)]
    assert bytes(first.frames.keyframes) == bytes(frame.keyframe for frame in video)
    assert (second.kind, second.codec_id, second.codec_private) == ("audio", "A_OPUS", OPUS_HEAD)
    assert (second.codec_delay, second.seek_pre_roll) == (6_500_000, 80_000_000)
    assert (second.sampling_frequency, second.channels, second.language) == (48000.0, 2, None)
    assert frames_of(data, second) == [frame_bytes(2, i, f.size) for i, f in enumerate(audio)]


def test_block_groups_are_keyframes_unless_they_reference_another_frame() -> None:
    frames = [Frame(0, 20, group=True), Frame(40, 20, keyframe=False, group=True)]
    data = webm_file([(VIDEO, [*frames, Frame(80, 20, keyframe=False)])])
    (track,) = index_webm(BytesSource(data))
    assert bytes(track.frames.keyframes) == b"\x01\x00\x00"
    assert frames_of(data, track) == [frame_bytes(1, index, 20) for index in range(3)]


def test_the_timestamp_scale_turns_ticks_into_nanoseconds() -> None:
    data = webm_file([(VIDEO, [Frame(0, 8), Frame(3, 8)])], scale=10_000_000, cluster_span=10)
    (track,) = index_webm(BytesSource(data))
    assert list(track.frames.times) == [0, 30_000_000]


def test_unknown_sizes_end_at_the_next_cluster_or_at_the_end() -> None:
    video = [Frame(index * 400, 16, keyframe=index % 3 == 0) for index in range(9)]
    data = webm_file([(VIDEO, video)], unknown_clusters=True, unknown_segment=True)
    (track,) = index_webm(BytesSource(data))
    assert frames_of(data, track) == [frame_bytes(1, index, 16) for index in range(9)]
    assert list(track.frames.times) == [index * 400_000_000 for index in range(9)]


def test_elements_around_the_clusters_are_skipped_and_matroska_is_read_too() -> None:
    cues = ebml.element(ebml.CUES, ebml.element(ebml.CUE_POINT, ebml.uint(ebml.CUE_TIME, 0)))
    data = webm_file([(VIDEO, [Frame(0, 8)])], trailer=cues, doctype="matroska")
    (track,) = index_webm(BytesSource(data))
    assert frames_of(data, track) == [frame_bytes(1, 0, 8)]


def test_colour_and_default_duration_are_kept() -> None:
    colour = ebml.element(ebml.COLOUR, ebml.uint(ebml.TRANSFER_CHARACTERISTICS, 16))
    spec = TrackSpec(colour=colour, default_duration=40_000_000)
    (track,) = index_webm(BytesSource(webm_file([(spec, [Frame(0, 8)])])))
    assert (track.colour, track.default_duration) == (colour, 40_000_000)


def test_tracks_without_frames_are_errors_unless_they_are_subtitles() -> None:
    subtitles = TrackSpec(number=2, kind=0x11, codec="S_TEXT/UTF8")
    data = webm_file([(VIDEO, [Frame(0, 8)]), (subtitles, [])])
    assert [track.number for track in index_webm(BytesSource(data))] == [1]
    with pytest.raises(MuxError, match=r"track 2 \(A_OPUS\) has no frames"):
        index_webm(BytesSource(webm_file([(VIDEO, [Frame(0, 8)]), (AUDIO, [])])))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"\x00\x00\x00\x20ftypisom" + bytes(24), "has no EBML header"),
        (b"", "has no EBML header"),
        (ebml.element(ebml.EBML, ebml.string(ebml.DOC_TYPE, "dvd")), "not WebM or Matroska"),
        (ebml.element(ebml.EBML, ebml.string(ebml.DOC_TYPE, "webm")) + b"\xec\x80", "no Segment"),
    ],
)
def test_other_inputs_are_refused(data: bytes, message: str) -> None:
    with pytest.raises(MuxError, match=message):
        index_webm(BytesSource(data))


def test_laced_blocks_are_refused() -> None:
    data = bytearray(webm_file([(VIDEO, [Frame(0, 8)])]))
    data[data.index(frame_bytes(1, 0, 8)) - 1] |= 0x02  # Xiph lacing
    with pytest.raises(MuxError, match="laced blocks"):
        index_webm(BytesSource(bytes(data)))


def test_a_block_before_the_cluster_timestamp_is_an_error() -> None:
    block = ebml.element(ebml.SIMPLE_BLOCK, b"\x81\x00\x00\x80", b"data")
    cluster = ebml.element(ebml.CLUSTER, block, ebml.uint(ebml.TIMESTAMP, 0))
    head = webm_file([(VIDEO, [Frame(0, 8)])])
    # The factory's file ends with its only cluster; replace the segment's content.
    header_end = head.index(ebml.encode_id(ebml.SEGMENT))
    tracks = ebml.element(ebml.TRACKS, *_entries(head))
    body = tracks + cluster
    data = head[:header_end] + ebml.element(ebml.SEGMENT, body)
    with pytest.raises(MuxError, match="before its timestamp"):
        index_webm(BytesSource(data))


def test_a_file_without_tracks_is_refused() -> None:
    header = webm_file([(VIDEO, [Frame(0, 8)])])
    data = header[: header.index(ebml.encode_id(ebml.SEGMENT))] + ebml.element(ebml.SEGMENT)
    with pytest.raises(MuxError, match="no Tracks"):
        index_webm(BytesSource(data))


def _entries(data: bytes) -> list[bytes]:
    """The TrackEntry elements of a factory file, whole."""
    start = data.index(ebml.encode_id(ebml.TRACKS))
    header = ebml.read_header(BytesSource(data), start)
    payload = data[header.payload_offset : header.end]
    return [ebml.element(element_id, value) for element_id, value in ebml.children(payload)]
