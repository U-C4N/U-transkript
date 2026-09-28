"""Tests for reading progressive MP4/MOV files back."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from tests.helpers.fmp4_factory import Track, payload, sample_entry
from utmax.core.media.boxes import BytesSource, box, u32, u64
from utmax.core.media.fmp4 import Edit
from utmax.core.media.moov import UNITY_MATRIX, Flavor, TrackPlan, ftyp_box, moov_box
from utmax.core.media.progressive import Chunk, Sample, parse_progressive
from utmax.core.media.tx3g import sample_entry as tx3g_entry
from utmax.errors import MuxError

VIDEO = TrackPlan(
    track_id=1,
    kind="video",
    timescale=12800,
    language="und",
    tag=None,
    name=None,
    enabled=True,
    matrix=UNITY_MATRIX,
    width=640 << 16,
    height=360 << 16,
    edits=(Edit(250, 512),),
    duration=250,
    media_duration=3072,
    sample_entries=(sample_entry(Track()), sample_entry(Track(width=320))),
    durations=[512] * 6,
    ctos=[1024, -512, 0, 512, 0, 0],
    sync=bytes([1, 0, 0, 1, 0, 0]),
    sizes=[40, 11, 12, 30, 13, 14],
    chunks=((3, 1), (2, 1), (1, 2)),
)
SUBTITLE = replace(
    VIDEO,
    track_id=2,
    kind="subtitle",
    timescale=1000,
    language="tur",
    tag="tr",
    name="Turkish",
    enabled=False,
    width=0,
    height=0,
    edits=(),
    duration=1500,
    media_duration=1500,
    sample_entries=(tx3g_entry(),),
    durations=[500, 1000],
    ctos=[0, 0],
    sync=bytes([1, 1]),
    sizes=[2, 9],
    chunks=((2, 1),),
)


def build(
    flavor: Flavor,
    tracks: Sequence[TrackPlan],
    *,
    wide: bool = False,
    large_mdat: bool = False,
    extra_offsets: int = 0,
) -> bytes:
    chunks: list[list[bytes]] = []
    for track in tracks:
        first, per_chunk = 0, []
        for count, _ in track.chunks:
            samples = range(first, first + count)
            per_chunk.append(b"".join(payload(track.track_id, i, track.sizes[i]) for i in samples))
            first += count
        chunks.append(per_chunk)
    body = b"".join(b"".join(track_chunks) for track_chunks in chunks)
    header = u32(1) + b"mdat" + u64(16 + len(body)) if large_mdat else u32(8 + len(body)) + b"mdat"
    ftyp = ftyp_box(flavor, {"avc1"})
    counts = [[0] * (len(track_chunks) + extra_offsets) for track_chunks in chunks]
    position = len(ftyp) + len(moov_box(flavor, tracks, counts, [wide] * len(tracks))) + len(header)
    offsets: list[list[int]] = []
    for track_chunks in chunks:
        offsets.append([])
        for chunk in track_chunks:
            offsets[-1].append(position)
            position += len(chunk)
        offsets[-1] += [position] * extra_offsets
    return ftyp + moov_box(flavor, tracks, offsets, [wide] * len(tracks)) + header + body


def test_movie_and_file_layout() -> None:
    parsed = parse_progressive(BytesSource(build("mp4", (VIDEO, SUBTITLE))))
    assert (parsed.major_brand, parsed.minor_version) == ("isom", 0x200)
    assert parsed.compatible_brands == ("isom", "iso2", "avc1", "mp41")
    assert [header.kind for header in parsed.boxes] == ["ftyp", "moov", "mdat"]
    assert (parsed.timescale, parsed.duration, parsed.next_track_id) == (1000, 1500, 3)


def test_video_track_samples_and_chunks() -> None:
    data = build("mp4", (VIDEO, SUBTITLE))
    video = parse_progressive(BytesSource(data)).tracks[0]
    assert (video.track_id, video.flags, video.alternate_group, video.volume) == (1, 3, 0, 0)
    assert (video.width, video.height, video.duration) == (640 << 16, 360 << 16, 250)
    assert video.edits == (Edit(250, 512),)
    assert (video.handler, video.handler_name, video.timescale) == ("vide", "VideoHandler", 12800)
    assert (video.media_duration, video.language, video.media_header) == (3072, 0x55C4, "vmhd")
    assert (video.extended_language, video.name, video.data_handler) == (None, None, False)
    assert len(video.sample_entries) == 2
    assert (video.chunk_box, video.ctts_version) == ("stco", 1)
    assert [chunk.count for chunk in video.chunks] == [3, 2, 1]
    assert [chunk.description for chunk in video.chunks] == [1, 1, 2]
    assert video.chunks[1] == Chunk(video.chunks[0].offset + 63, 3, 2, 1)
    assert [sample.dts for sample in video.samples] == [0, 512, 1024, 1536, 2048, 2560]
    assert [sample.cto for sample in video.samples] == [1024, -512, 0, 512, 0, 0]
    assert [sample.sync for sample in video.samples] == [True, False, False, True, False, False]
    assert video.samples[5] == Sample(video.chunks[2].offset, 14, 2560, 512, 0, False, 2)
    for index, sample in enumerate(video.samples):
        assert data[sample.offset : sample.offset + sample.size] == payload(1, index, sample.size)


def test_subtitle_track_details() -> None:
    subtitle = parse_progressive(BytesSource(build("mp4", (VIDEO, SUBTITLE)))).tracks[1]
    assert (subtitle.flags, subtitle.alternate_group, subtitle.media_header) == (2, 3, "nmhd")
    assert (subtitle.handler, subtitle.handler_name) == ("sbtl", "Turkish")
    assert (subtitle.extended_language, subtitle.name) == ("tr", "Turkish")
    assert subtitle.ctts_version is None
    assert all(sample.sync for sample in subtitle.samples)


def test_quicktime_files_have_pascal_handler_names_and_a_data_handler() -> None:
    parsed = parse_progressive(BytesSource(build("mov", (VIDEO, SUBTITLE))))
    assert parsed.major_brand == "qt  "
    assert [track.handler_name for track in parsed.tracks] == ["VideoHandler", "Turkish"]
    assert all(track.data_handler for track in parsed.tracks)
    assert parsed.tracks[1].language == 17


def test_co64_and_64_bit_mdat_headers() -> None:
    parsed = parse_progressive(BytesSource(build("mp4", (VIDEO,), wide=True, large_mdat=True)))
    mdat = parsed.boxes[2]
    assert (mdat.kind, mdat.header_size) == ("mdat", 16)
    assert parsed.tracks[0].chunk_box == "co64"
    assert parsed.tracks[0].samples[0].offset == mdat.payload_offset


def test_version_1_movie_headers() -> None:
    long = replace(SUBTITLE, duration=2**31, media_duration=2**31)
    parsed = parse_progressive(BytesSource(build("mp4", (long,))))
    assert parsed.duration == 2**31
    assert (parsed.tracks[0].duration, parsed.tracks[0].media_duration) == (2**31, 2**31)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (box("ftyp", b"isom", u32(0)), "no top-level 'moov'"),
        (box("moov"), "no top-level 'ftyp'"),
    ],
)
def test_missing_boxes(data: bytes, message: str) -> None:
    with pytest.raises(MuxError, match=message):
        parse_progressive(BytesSource(data))


def test_sample_tables_that_disagree_are_errors() -> None:
    uneven = replace(VIDEO, durations=[512] * 7)
    with pytest.raises(MuxError, match="disagree about the number of samples"):
        parse_progressive(BytesSource(build("mp4", (uneven,))))


def test_chunks_listing_too_many_or_too_few_samples_are_errors() -> None:
    with pytest.raises(MuxError, match="more samples than the sample tables"):
        parse_progressive(BytesSource(build("mp4", (VIDEO,), extra_offsets=1)))
    short = replace(VIDEO, chunks=((3, 1), (2, 1)))
    with pytest.raises(MuxError, match="fewer samples than the sample tables"):
        parse_progressive(BytesSource(build("mp4", (short,))))


def test_a_sample_to_chunk_table_that_skips_chunks_is_an_error() -> None:
    data = build("mp4", (VIDEO,))
    stsc = data.index(b"stsc")
    patched = data[: stsc + 24] + u32(9) + data[stsc + 28 :]  # second entry starts at chunk 9
    with pytest.raises(MuxError, match="does not match the number of chunks"):
        parse_progressive(BytesSource(patched))
