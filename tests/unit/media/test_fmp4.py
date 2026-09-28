"""Tests for indexing fragmented MP4 streams, flag path by flag path."""

from __future__ import annotations

import pytest

from tests.helpers.fmp4_factory import (
    NON_SYNC_FLAGS,
    SYNC_FLAGS,
    Run,
    Sample,
    Track,
    Traf,
    fragmented_file,
    init_segment,
    payload,
    simple_file,
)
from utmax.core.media.boxes import BytesSource, box, full_box, i32, i64, u32, u64
from utmax.core.media.fmp4 import Edit, IndexedTrack, index_fragments, parse_elst
from utmax.errors import MuxError

VIDEO = Track()
AUDIO = Track(track_id=2, handler="soun", codec="mp4a", timescale=44100)


def index_one(data: bytes) -> IndexedTrack:
    (track,) = index_fragments(BytesSource(data))
    return track


def assert_samples(
    data: bytes, track: IndexedTrack, expected: list[Sample], first_dts: int = 0
) -> None:
    table = track.samples
    assert list(table.sizes) == [sample.size for sample in expected]
    assert list(table.ctos) == [sample.cto for sample in expected]
    assert [bool(flag) for flag in table.sync] == [sample.sync for sample in expected]
    decode_time = first_dts
    for index, sample in enumerate(expected):
        assert table.dts[index] == decode_time
        decode_time += sample.duration
        start = table.offsets[index]
        assert data[start : start + sample.size] == payload(
            track.header.track_id, index, sample.size
        )
    assert list(table.durations) == [sample.duration for sample in expected]


def test_youtube_h264_layout_default_duration_and_signed_offsets() -> None:
    # itag 137: tfhd 0x02000a (base is moof, sample description, default duration),
    # trun 0x000e01 (data offset, per-sample size, flags and composition offset).
    samples = [Sample(512, 900 + i, sync=i == 0, cto=(0, 512, 1536, 0)[i % 4]) for i in range(8)]
    fragments = [
        [
            Traf(
                1,
                (Run(tuple(samples[:4]), flags=0x000E01),),
                flags=0x02000A,
                default_duration=512,
            )
        ],
        [
            Traf(
                1,
                (Run(tuple(samples[4:]), flags=0x000E01),),
                flags=0x02000A,
                default_duration=512,
                tfdt=2048,
            )
        ],
    ]
    data = fragmented_file([VIDEO], fragments)
    track = index_one(data)
    assert track.header.codec == "avc1"
    assert (track.header.handler, track.header.timescale) == ("vide", 12800)
    assert_samples(data, track, samples)


def test_youtube_aac_layout_uses_tfhd_default_flags() -> None:
    # itag 140: tfhd 0x02002a (default duration and flags), trun 0x000201 (sizes only).
    samples = [Sample(1024, 300 + i) for i in range(5)]
    traf = Traf(
        2,
        (Run(tuple(samples), flags=0x000201),),
        flags=0x02002A,
        default_duration=1024,
        default_flags=SYNC_FLAGS,
    )
    data = fragmented_file([AUDIO], [[traf]])
    track = index_one(data)
    assert track.header.codec == "mp4a"
    assert_samples(data, track, samples)


def test_youtube_av1_layout_with_per_sample_flags() -> None:
    # itag 399: trun 0x000601 (data offset, sizes, flags), duration from tfhd.
    samples = [Sample(512, 50 + i, sync=i == 0) for i in range(4)]
    traf = Traf(1, (Run(tuple(samples), flags=0x000601),), flags=0x02000A, default_duration=512)
    data = fragmented_file([Track(codec="av01")], [[traf]])
    assert_samples(data, index_one(data), samples)


def test_values_fall_back_to_trex_defaults() -> None:
    samples = [Sample(1000, 40, sync=False) for _ in range(3)]
    track = Track(trex=(1, 1000, 40, NON_SYNC_FLAGS))
    data = fragmented_file([track], [[Traf(1, (Run(tuple(samples), flags=0x000001),))]])
    assert_samples(data, index_one(data), samples)


def test_first_sample_flags_mark_only_the_first_sample() -> None:
    samples = [Sample(512, 10, sync=i == 0) for i in range(4)]
    run = Run(tuple(samples), flags=0x000205)  # data offset, first-sample flags, sizes
    traf = Traf(1, (run,), flags=0x020028, default_duration=512, default_flags=NON_SYNC_FLAGS)
    data = fragmented_file([VIDEO], [[traf]])
    assert_samples(data, index_one(data), samples)


def test_version_1_runs_carry_negative_composition_offsets() -> None:
    samples = [Sample(512, 10, cto=cto) for cto in (0, 1024, -512, -512)]
    data = simple_file(samples, run_version=1)
    assert_samples(data, index_one(data), samples)


def test_version_0_runs_are_read_as_signed_like_ffmpeg_does() -> None:
    samples = [Sample(512, 10, cto=cto) for cto in (0, 1024, -512, -512)]
    data = simple_file(samples, run_version=0)
    assert_samples(data, index_one(data), samples)


def test_tfdt_version_1_keeps_64_bit_decode_times() -> None:
    samples = [Sample(512, 10) for _ in range(3)]
    base = 2**33
    traf = Traf(1, (Run(tuple(samples)),), tfdt=base, tfdt_version=1)
    data = fragmented_file([VIDEO], [[traf]])
    assert_samples(data, index_one(data), samples, first_dts=base)


def test_without_tfdt_decode_time_continues_from_the_previous_fragment() -> None:
    samples = [Sample(512, 10) for _ in range(4)]
    fragments = [
        [Traf(1, (Run(tuple(samples[:2])),), tfdt=None)],
        [Traf(1, (Run(tuple(samples[2:])),), tfdt=None)],
    ]
    data = fragmented_file([VIDEO], fragments)
    assert_samples(data, index_one(data), samples)


def test_runs_without_data_offset_follow_the_previous_run() -> None:
    samples = [Sample(512, 10 + i) for i in range(6)]
    runs = (
        Run(tuple(samples[:2])),
        Run(tuple(samples[2:4]), flags=0x000F00),
        Run(tuple(samples[4:]), flags=0x000F00),
    )
    data = fragmented_file([VIDEO], [[Traf(1, runs)]])
    assert_samples(data, index_one(data), samples)


def test_explicit_base_data_offset() -> None:
    samples = [Sample(512, 10 + i) for i in range(3)]
    traf = Traf(1, (Run(tuple(samples), flags=0x000F00),), flags=0x000001)
    data = fragmented_file([VIDEO], [[traf]])
    assert_samples(data, index_one(data), samples)


def test_implicit_base_of_a_second_track_fragment_is_the_end_of_the_first() -> None:
    video = [Sample(512, 100), Sample(512, 110)]
    audio = [Sample(1024, 7), Sample(1024, 8)]
    fragment = [
        Traf(1, (Run(tuple(video)),), flags=0),
        Traf(2, (Run(tuple(audio), flags=0x000F00),), flags=0),
    ]
    data = fragmented_file([VIDEO, AUDIO], [fragment])
    video_track, audio_track = index_fragments(BytesSource(data))
    assert_samples(data, video_track, video)
    assert_samples(data, audio_track, audio)


def test_duration_is_empty_fragments_stretch_the_previous_sample() -> None:
    fragments = [
        [Traf(1, (Run((Sample(512, 10), Sample(512, 11))),))],
        [Traf(1, (), flags=0x030008, default_duration=2000, tfdt=None)],
        [Traf(1, (Run((Sample(512, 12),)),), tfdt=None)],
    ]
    track = index_one(fragmented_file([VIDEO], fragments))
    assert list(track.samples.dts) == [0, 512, 3024]
    assert list(track.samples.durations) == [512, 2512, 512]


def test_a_later_tfdt_turns_a_gap_into_a_longer_previous_sample() -> None:
    fragments = [
        [Traf(1, (Run((Sample(512, 10), Sample(512, 11))),))],
        [Traf(1, (Run((Sample(512, 12),)),), tfdt=5000)],
    ]
    track = index_one(fragmented_file([VIDEO], fragments))
    assert list(track.samples.durations) == [512, 4488, 512]


def test_decode_times_going_backwards_are_an_error() -> None:
    fragments = [
        [Traf(1, (Run((Sample(512, 10), Sample(512, 11))),), tfdt=1000)],
        [Traf(1, (Run((Sample(512, 12),)),), tfdt=100)],
    ]
    with pytest.raises(MuxError, match="go backwards in track 1"):
        index_fragments(BytesSource(fragmented_file([VIDEO], fragments)))


def test_sample_description_index_is_recorded_and_checked() -> None:
    track = Track(entries=2)
    good = Traf(1, (Run((Sample(512, 10),)),), flags=0x020002, description=2)
    indexed = index_one(fragmented_file([track], [[good]]))
    assert list(indexed.samples.descriptions) == [2]
    assert len(indexed.header.sample_entries) == 2
    bad = Traf(1, (Run((Sample(512, 10),)),), flags=0x020002, description=3)
    with pytest.raises(MuxError, match="sample description 3, but only 2 exist"):
        index_fragments(BytesSource(fragmented_file([track], [[bad]])))


@pytest.mark.parametrize(
    "noise",
    [
        box("styp", b"msdh"),
        box("sidx", bytes(24)),
        box("emsg", bytes(12)),
        box("prft", bytes(20)),
        box("free", b"x"),
        box("uuid", bytes(16)),
        box("abcd", b"unknown"),
    ],
)
def test_other_top_level_boxes_are_skipped(noise: bytes) -> None:
    samples = [Sample(512, 10 + i) for i in range(4)]
    fragments = [
        [Traf(1, (Run(tuple(samples[:2])),))],
        [Traf(1, (Run(tuple(samples[2:])),), tfdt=1024)],
    ]
    data = fragmented_file([VIDEO], fragments, after_moov=noise, between=noise)
    assert_samples(data, index_one(data), samples)


def test_track_headers() -> None:
    track = Track(width=1920, height=1080, language="eng", edits=((5000, 512),))
    data = fragmented_file([track], [[Traf(1, (Run((Sample(512, 10),)),))]], movie_timescale=600)
    header = index_one(data).header
    assert header.track_id == 1
    assert (header.width, header.height) == (1920 << 16, 1080 << 16)
    assert header.language == 0x15C7  # "eng" packed as three 5-bit letters
    assert header.edits == (Edit(5000, 512),)
    assert header.movie_timescale == 600
    assert len(header.matrix) == 36


def test_version_1_movie_track_and_media_headers() -> None:
    fragments = [[Traf(1, (Run((Sample(512, 10),)),))]]
    header = index_one(fragmented_file([VIDEO], fragments, header_version=1)).header
    assert (header.timescale, header.movie_timescale) == (12800, 1000)


def test_parse_elst_versions_0_and_1() -> None:
    version_0 = full_box(
        "elst", 0, 0, u32(2), u32(100), i32(-1), u32(0x10000), u32(9), i32(3), u32(0x10000)
    )
    assert parse_elst(version_0[8:]) == (Edit(100, -1), Edit(9, 3))
    version_1 = full_box("elst", 1, 0, u32(1), u64(2**40), i64(2**33), u32(0x8000))
    assert parse_elst(version_1[8:]) == (Edit(2**40, 2**33, 0x8000),)


def patched(data: bytes, marker: bytes, offset: int, value: bytes) -> bytes:
    position = data.index(marker) + offset
    return data[:position] + value + data[position + len(value) :]


ONE_SAMPLE = [[Traf(1, (Run((Sample(512, 10),)),))]]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (box("ftyp", b"isom"), "no 'moov' box"),
        (bytes.fromhex("1a45dfa3") + bytes(60), "impossible size"),  # a WebM (EBML) file
        (
            box("moof") + init_segment([VIDEO]),
            "'moof' box before its 'moov' box",
        ),
        (init_segment([VIDEO]) + init_segment([VIDEO])[24:], "two 'moov' boxes"),
        (init_segment([VIDEO], fragmented=False), "not a fragmented MP4"),
        (init_segment([VIDEO], samples_in_moov=True), "keeps samples in its 'moov'"),
        (init_segment([VIDEO]), "Track 1 of the input has no samples"),
        (init_segment([]), "has no tracks"),
        (init_segment([VIDEO, VIDEO]), "declares track 1 twice"),
        (init_segment([Track(timescale=0)]), "zero timescale"),
        (init_segment([Track(entries=0)]), "no sample descriptions"),
    ],
)
def test_broken_init_segments(data: bytes, message: str) -> None:
    with pytest.raises(MuxError, match=message):
        index_fragments(BytesSource(data))


def test_fragments_must_name_a_known_track() -> None:
    data = patched(fragmented_file([VIDEO], ONE_SAMPLE), b"tfhd", 8, u32(9))
    with pytest.raises(MuxError, match="refers to track 9"):
        index_fragments(BytesSource(data))


def test_track_fragments_need_a_tfhd() -> None:
    data = patched(fragmented_file([VIDEO], ONE_SAMPLE), b"tfhd", 0, b"xxxx")
    with pytest.raises(MuxError, match="no 'tfhd' box"):
        index_fragments(BytesSource(data))


def test_truncated_runs_are_an_error() -> None:
    data = patched(fragmented_file([VIDEO], ONE_SAMPLE), b"trun", 8, u32(99))
    with pytest.raises(MuxError, match="lists 99 samples but is too short"):
        index_fragments(BytesSource(data))


def test_sample_descriptions_with_impossible_sizes_are_an_error() -> None:
    data = patched(init_segment([VIDEO]), b"avc1", -4, u32(4))
    with pytest.raises(MuxError, match="impossible size"):
        index_fragments(BytesSource(data))


@pytest.mark.parametrize(
    ("shift", "message"), [(-50, "outside every 'mdat'"), (-(10**6), "before the start")]
)
def test_sample_data_must_lie_inside_an_mdat(shift: int, message: str) -> None:
    data = fragmented_file([VIDEO], [[Traf(1, (Run((Sample(512, 10),), shift=shift),))]])
    with pytest.raises(MuxError, match=message):
        index_fragments(BytesSource(data))


def test_truncated_inputs_are_reported() -> None:
    data = fragmented_file([VIDEO], ONE_SAMPLE)
    with pytest.raises(MuxError, match="impossible size"):
        index_fragments(BytesSource(data[:-3]))


def test_empty_runs_and_other_mvex_children_are_ignored() -> None:
    samples = [Sample(512, 10)]
    init = init_segment([VIDEO], mvex_extra=full_box("mehd", 0, 0, u32(0)))
    body = fragmented_file([VIDEO], [[Traf(1, (Run(()), Run(tuple(samples))))]])
    data = init + body[len(init_segment([VIDEO])) :]
    assert_samples(data, index_one(data), samples)


def test_a_moov_without_stsz_is_accepted() -> None:
    data = patched(fragmented_file([VIDEO], ONE_SAMPLE), b"stsz", 0, b"stz2")
    assert len(index_one(data).samples) == 1
