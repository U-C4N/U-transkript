"""Tests for the Matroska/WebM writer and the shared media model it reads."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.downloads import AUDIO_BYTES, AV1_BYTES
from tests.helpers.fmp4_factory import Sample, Track, simple_file
from tests.helpers.webm_factory import OPUS_HEAD, Frame, TrackSpec, frame_bytes, webm_file
from utmax.core.media import ebml
from utmax.core.media.boxes import BytesSource
from utmax.core.media.ebml import ElementHeader
from utmax.core.media.matroska import plan_matroska
from utmax.core.media.model import MediaTrack, media_tracks
from utmax.core.media.mux import PlanSource
from utmax.core.media.webm import index_webm
from utmax.errors import InvalidOption, MuxError
from utmax.models import Segment

VP9 = webm_file(
    [
        (
            TrackSpec(width=3840, height=2160),
            [Frame(index * 40, 200 + index % 30, keyframe=index % 25 == 0) for index in range(100)],
        )
    ]
)
OPUS = webm_file(
    [
        (
            TrackSpec(
                kind=2,
                codec="A_OPUS",
                private=OPUS_HEAD,
                codec_delay=6_500_000,
                seek_pre_roll=80_000_000,
                language=None,
            ),
            [Frame(index * 20, 60 + index % 7) for index in range(200)],
        )
    ]
)


def tracks_of(*inputs: tuple[bytes, str]) -> tuple[list[BytesSource], list[MediaTrack]]:
    sources = [BytesSource(data) for data, _ in inputs]
    tracks = [
        track
        for number, ((_, container), source) in enumerate(zip(inputs, sources, strict=True))
        for track in media_tracks(source, number, container=container)
    ]
    return sources, tracks


def write(*inputs: tuple[bytes, str], doctype: str = "matroska", **options: object) -> bytes:
    sources, tracks = tracks_of(*inputs)
    plan = plan_matroska(tracks, doctype=doctype, **options)  # type: ignore[arg-type]
    return PlanSource(plan, sources).read(0, plan.size)


def segment(data: bytes) -> tuple[int, list[ElementHeader]]:
    """Where the Segment's payload starts, and the headers of its children."""
    source = BytesSource(data)
    header = ebml.read_header(source, 0)
    seg = ebml.read_header(source, header.end)
    assert seg.end == len(data)
    found, position = [], seg.payload_offset
    while position < seg.end:
        child = ebml.read_header(source, position)
        found.append(child)
        position = child.end
    return seg.payload_offset, found


def payload(data: bytes, header: ElementHeader) -> bytes:
    return data[header.payload_offset : header.end]


def entries(data: bytes) -> list[dict[int, bytes]]:
    _, children = segment(data)
    (tracks,) = [child for child in children if child.element_id == ebml.TRACKS]
    return [dict(ebml.children(entry)) for _, entry in ebml.children(payload(data, tracks))]


def blocks(data: bytes) -> list[list[tuple[int, int, int, bytes]]]:
    """Every cluster as ``(track, absolute ms, flags, data)`` of its blocks, in order."""
    _, children = segment(data)
    found = []
    for cluster in (child for child in children if child.element_id == ebml.CLUSTER):
        start, items = 0, []
        for element_id, value in ebml.children(payload(data, cluster)):
            if element_id == ebml.TIMESTAMP:
                start = ebml.uint_value(value)
            elif element_id in (ebml.SIMPLE_BLOCK, ebml.BLOCK_GROUP):
                block = (
                    value
                    if element_id == ebml.SIMPLE_BLOCK
                    else dict(ebml.children(value))[ebml.BLOCK]
                )
                track, length = ebml.read_vint(block, 0)
                relative = int.from_bytes(block[length : length + 2], "big", signed=True)
                items.append((track, start + relative, block[length + 2], block[length + 3 :]))
        found.append(items)
    return found


def test_webm_and_mp4_sources_are_copied_frame_for_frame() -> None:
    data = write((VP9, "webm"), (OPUS, "webm"), (AUDIO_BYTES, "mp4"))
    video, opus, aac = index_webm(BytesSource(data))
    assert [
        data[o : o + s] for o, s in zip(video.frames.offsets, video.frames.sizes, strict=True)
    ] == [frame_bytes(1, index, 200 + index % 30) for index in range(100)]
    assert list(video.frames.times) == [index * 40_000_000 for index in range(100)]
    assert bytes(video.frames.keyframes) == bytes(index % 25 == 0 for index in range(100))
    assert [
        data[o : o + s] for o, s in zip(opus.frames.offsets, opus.frames.sizes, strict=True)
    ] == [frame_bytes(1, index, 60 + index % 7) for index in range(200)]
    assert (opus.codec_id, opus.codec_private, opus.codec_delay, opus.seek_pre_roll) == (
        "A_OPUS",
        OPUS_HEAD,
        6_500_000,
        80_000_000,
    )
    _, (source,) = tracks_of((AUDIO_BYTES, "mp4"))
    assert (aac.codec_id, len(aac.frames)) == ("A_AAC", len(source.sizes))
    assert list(aac.frames.times) == [round(t / 1e6) * 1_000_000 for t in source.times]


def test_the_seek_head_and_the_cues_point_at_what_they_name() -> None:
    data = write((VP9, "webm"), (OPUS, "webm"))
    start, children = segment(data)
    assert [child.element_id for child in children[:4]] == [
        ebml.SEEK_HEAD,
        ebml.INFO,
        ebml.TRACKS,
        ebml.CUES,
    ]
    seeks = [dict(ebml.children(seek)) for _, seek in ebml.children(payload(data, children[0]))]
    for seek in seeks:
        target = ebml.read_header(
            BytesSource(data), start + ebml.uint_value(seek[ebml.SEEK_POSITION])
        )
        assert ebml.encode_id(target.element_id) == seek[ebml.SEEK_ID]
    cue_points = [
        dict(ebml.children(point)) for _, point in ebml.children(payload(data, children[3]))
    ]
    assert [ebml.uint_value(point[ebml.CUE_TIME]) for point in cue_points] == [0, 1000, 2000, 3000]
    clusters = [child.offset for child in children if child.element_id == ebml.CLUSTER]
    contents = blocks(data)
    for point in cue_points:
        position = dict(ebml.children(point[ebml.CUE_TRACK_POSITIONS]))
        assert ebml.uint_value(position[ebml.CUE_TRACK]) == 1
        at = start + ebml.uint_value(position[ebml.CUE_CLUSTER_POSITION])
        assert at in clusters
        first_video = next(item for item in contents[clusters.index(at)] if item[0] == 1)
        assert first_video[1:3] == (ebml.uint_value(point[ebml.CUE_TIME]), 0x80)


def test_clusters_start_at_video_keyframes_and_last_at_most_five_seconds() -> None:
    long_gop = webm_file(
        [(TrackSpec(), [Frame(index * 40, 50, keyframe=index % 300 == 0) for index in range(600)])]
    )
    clusters = blocks(write((long_gop, "webm"), (OPUS, "webm")))
    starts = [min(item[1] for item in cluster) for cluster in clusters]
    assert starts == [0, 5000, 10000, 12000, 17000, 22000]
    assert all(later - earlier <= 5000 for earlier, later in pairwise(starts))
    assert [cluster[0][2] for cluster in clusters if cluster[0][0] == 1][:1] == [0x80]


def test_audio_only_files_get_a_cluster_and_a_cue_every_five_seconds() -> None:
    long_opus = webm_file(
        [
            (
                TrackSpec(kind=2, codec="A_OPUS", private=OPUS_HEAD),
                [Frame(index * 20, 10) for index in range(600)],
            )
        ]
    )
    data = write((long_opus, "webm"), doctype="webm")
    assert [min(item[1] for item in cluster) for cluster in blocks(data)] == [0, 5000, 10000]
    _, children = segment(data)
    (cues,) = [child for child in children if child.element_id == ebml.CUES]
    assert len(ebml.children(payload(data, cues))) == 3


def test_tracks_say_what_they_hold_and_the_first_of_each_kind_is_default() -> None:
    data = write((VP9, "webm"), (AV1_BYTES, "mp4"), (OPUS, "webm"), (AUDIO_BYTES, "mp4"))
    found = entries(data)
    assert [entry[ebml.CODEC_ID] for entry in found] == [b"V_VP9", b"V_AV1", b"A_OPUS", b"A_AAC"]
    assert [ebml.uint_value(entry[ebml.FLAG_DEFAULT]) for entry in found] == [1, 0, 1, 0]
    assert all(ebml.uint_value(entry[ebml.FLAG_LACING]) == 0 for entry in found)
    assert [ebml.uint_value(entry[ebml.TRACK_TYPE]) for entry in found] == [1, 1, 2, 2]
    video = dict(ebml.children(found[0][ebml.VIDEO]))
    assert (
        ebml.uint_value(video[ebml.PIXEL_WIDTH]),
        ebml.uint_value(video[ebml.PIXEL_HEIGHT]),
    ) == (3840, 2160)
    sound = dict(ebml.children(found[3][ebml.AUDIO]))
    assert (
        ebml.float_value(sound[ebml.SAMPLING_FREQUENCY]),
        ebml.uint_value(sound[ebml.CHANNELS]),
    ) == (44100.0, 2)


def test_webm_takes_vp9_av1_and_opus_without_subtitles() -> None:
    data = write((VP9, "webm"), (OPUS, "webm"), doctype="webm")
    assert b"\x42\x82\x84webm" in data[:64]
    with pytest.raises(MuxError, match=r"A_AAC track cannot go into a \.webm file"):
        write((VP9, "webm"), (AUDIO_BYTES, "mp4"), doctype="webm")
    with pytest.raises(MuxError, match="WebM files cannot hold subtitle tracks"):
        write(
            (VP9, "webm"),
            (OPUS, "webm"),
            doctype="webm",
            subtitles=[make_transcript(Segment(0, 1, "x"))],
        )


def test_subtitles_are_text_tracks_with_durations_cut_at_the_end_of_the_media() -> None:
    english = make_transcript(
        Segment(0.5, 1.0, "Hello <i>there</i>"),
        Segment(3.9, 5.0, "Last"),
        Segment(9.0, 1.0, "Too late"),
    )
    turkish = replace(
        make_transcript(Segment(1.0, 1.0, "Merhaba"), language_code="tr", language="Turkish"),
        translator="grok=grok-4.7",
    )
    data = write((VP9, "webm"), (OPUS, "webm"), subtitles=[english, turkish], default_subtitle="tr")
    found = entries(data)
    english_entry, turkish_entry = found[2], found[3]
    assert english_entry[ebml.CODEC_ID] == b"S_TEXT/UTF8"
    assert (
        ebml.uint_value(english_entry[ebml.TRACK_TYPE]),
        english_entry[ebml.LANGUAGE],
        english_entry[ebml.LANGUAGE_BCP47],
    ) == (0x11, b"eng", b"en")
    assert [
        ebml.uint_value(entry[ebml.FLAG_DEFAULT]) for entry in (english_entry, turkish_entry)
    ] == [0, 1]
    assert turkish_entry[ebml.NAME] == b"Turkish (AI: grok=grok-4.7)"
    texts = [
        (track, time, text)
        for cluster in blocks(data)
        for track, time, _, text in cluster
        if track >= 3
    ]
    assert texts == [(3, 500, b"Hello there"), (4, 1000, b"Merhaba"), (3, 3900, b"Last")]
    _, children = segment(data)
    groups = [
        dict(ebml.children(value))
        for cluster in children
        if cluster.element_id == ebml.CLUSTER
        for element_id, value in ebml.children(payload(data, cluster))
        if element_id == ebml.BLOCK_GROUP
    ]
    assert [ebml.uint_value(group[ebml.BLOCK_DURATION]) for group in groups] == [1000, 1000, 100]


def test_a_default_subtitle_that_is_not_there_is_refused() -> None:
    with pytest.raises(InvalidOption, match="matches no embedded subtitle"):
        write(
            (VP9, "webm"),
            (OPUS, "webm"),
            subtitles=[make_transcript(Segment(0, 1, "x"))],
            default_subtitle="de",
        )


def test_equal_inputs_give_equal_bytes() -> None:
    first = write(
        (VP9, "webm"), (AUDIO_BYTES, "mp4"), subtitles=[make_transcript(Segment(0, 1, "x"))]
    )
    second = write(
        (VP9, "webm"), (AUDIO_BYTES, "mp4"), subtitles=[make_transcript(Segment(0, 1, "x"))]
    )
    assert first == second


def test_b_frames_keep_decode_order_with_presentation_times_after_the_edit() -> None:
    # Decode order I P B B; shown 0, 3, 1, 2 frames after the 1024-tick reorder delay.
    samples = [
        Sample(512, 100, sync=True, cto=1024),
        Sample(512, 101, sync=False, cto=2048),
        Sample(512, 102, sync=False, cto=512),
        Sample(512, 103, sync=False, cto=512),
    ]
    data = simple_file(samples, track=Track(edits=((160, 1024),)))
    _, (track,) = tracks_of((data, "mp4"))
    assert list(track.times) == [0, 120_000_000, 40_000_000, 80_000_000]
    assert list(track.decode_times) == [-80_000_000, -40_000_000, 0, 40_000_000]
    output = write((data, "mp4"))
    assert [(time, flags, len(frame)) for _, time, flags, frame in blocks(output)[0]] == [
        (0, 0x80, 100),
        (120, 0, 101),
        (40, 0, 102),
        (80, 0, 103),
    ]


def test_audio_priming_the_edit_list_hides_is_dropped_and_empty_edits_delay() -> None:
    audio = Track(handler="soun", codec="mp4a", timescale=44100, edits=((100, 1024),))
    _, (track,) = tracks_of(
        (simple_file([Sample(1024, 50 + n) for n in range(5)], track=audio), "mp4")
    )
    assert list(track.sizes) == [51, 52, 53, 54]  # the first frame ended before the start
    assert track.times[0] == 0
    delayed = Track(handler="soun", codec="mp4a", timescale=44100, edits=((500, -1), (100, 0)))
    _, (late,) = tracks_of((simple_file([Sample(1024, 50)], track=delayed), "mp4"))
    assert late.times[0] == 500_000_000


@pytest.mark.parametrize("doctype", ["avi", "mp4"])
def test_unknown_doctypes_are_refused(doctype: str) -> None:
    with pytest.raises(MuxError, match="Unknown Matroska doctype"):
        write((VP9, "webm"), doctype=doctype)


def test_nothing_to_mux_and_too_many_tracks_are_refused() -> None:
    with pytest.raises(MuxError, match="nothing to mux"):
        plan_matroska([], doctype="matroska")
    _, tracks = tracks_of((OPUS, "webm"))
    with pytest.raises(MuxError, match="at most 126 tracks"):
        plan_matroska(tracks * 127, doctype="matroska")


def test_a_track_without_frames_cannot_exist() -> None:
    _, (track,) = tracks_of((OPUS, "webm"))
    with pytest.raises(MuxError, match="has no frames"):
        replace(track, sizes=[], offsets=[], times=[], decode_times=[], keyframes=b"")
