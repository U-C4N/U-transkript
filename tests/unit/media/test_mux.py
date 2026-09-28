"""Tests for planning progressive files from fragmented media streams."""

from __future__ import annotations

from fractions import Fraction

import pytest

from tests.helpers.fmp4_factory import Run, Sample, Track, Traf, fragmented_file, simple_file
from tests.helpers.hollow_source import HollowSource
from tests.unit.media.invariants import check_file
from utmax.core.media.boxes import BytesSource, Reader, child_boxes
from utmax.core.media.fmp4 import Edit, index_fragments
from utmax.core.media.mux import Blob, CopyOp, MuxPlan, PlanSource, convert_edits, plan_mux
from utmax.core.media.progressive import Track as ParsedTrack
from utmax.errors import MuxError

VIDEO = Track(edits=((0, 1024),))
AUDIO = Track(handler="soun", codec="mp4a", timescale=44100)
B_FRAME_OFFSETS = (1024, 2048, 512, 512)


def video_samples(seconds: int = 3) -> list[Sample]:
    return [
        Sample(512, 900 + (i * 37) % 400, sync=i % 25 == 0, cto=B_FRAME_OFFSETS[i % 4])
        for i in range(25 * seconds)
    ]


def audio_samples(seconds: int = 3) -> list[Sample]:
    return [Sample(1024, 200 + (i * 13) % 90) for i in range(43 * seconds)]


def video_file(seconds: int = 3, track: Track = VIDEO) -> BytesSource:
    return BytesSource(simple_file(video_samples(seconds), track=track, per_fragment=25))


def audio_file(seconds: int = 3, track: Track = AUDIO) -> BytesSource:
    return BytesSource(simple_file(audio_samples(seconds), track=track, per_fragment=43))


def test_mp4_keeps_every_sample_and_its_bytes() -> None:
    sources = [video_file(), audio_file()]
    parsed = check_file(plan_mux(sources, flavor="mp4"), sources)
    assert parsed.major_brand == "isom"
    assert parsed.compatible_brands == ("isom", "iso2", "avc1", "mp41")
    video, audio = parsed.tracks
    assert (video.track_id, video.handler, video.flags, video.alternate_group) == (1, "vide", 3, 0)
    assert (audio.track_id, audio.handler, audio.flags, audio.alternate_group) == (2, "soun", 3, 1)
    assert video.ctts_version == 0
    assert (len(video.chunks), len(audio.chunks)) == (3, 3)


def test_negative_composition_offsets_are_kept_with_ctts_version_1() -> None:
    samples = [Sample(512, 100, sync=i == 0, cto=(0, 1024, -512, -512)[i % 4]) for i in range(8)]
    sources = [BytesSource(simple_file(samples, run_version=1))]
    video = check_file(plan_mux(sources, flavor="mp4"), sources).tracks[0]
    assert video.ctts_version == 1


def test_source_edit_lists_are_kept_in_milliseconds() -> None:
    sources = [video_file(), audio_file()]
    video, audio = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    samples = video_samples()
    presentation_end = max(
        512 * i + sample.cto + sample.duration for i, sample in enumerate(samples)
    )
    assert presentation_end == 39936
    assert video.edits == (Edit(3040, 1024),)  # (39936 - 1024) ticks at 12800 Hz, in ms
    assert video.duration == 3040
    assert audio.edits == ()
    assert audio.duration == 2996  # 129 * 1024 ticks at 44100 Hz, rounded up


def test_edit_durations_are_cut_to_the_media_that_exists() -> None:
    long_edit = Track(edits=((2_727_936, 512),))  # YouTube states the full length (213 s)
    sources = [video_file(track=long_edit)]
    (video,) = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    assert video.edits == (Edit(3080, 512),)  # (39936 - 512) ticks at 12800 Hz, in ms


def test_a_later_start_becomes_a_leading_empty_edit() -> None:
    late_audio = BytesSource(
        fragmented_file([AUDIO], [[Traf(1, (Run(tuple(audio_samples(1))),), tfdt=22050)]])
    )
    sources = [video_file(1), late_audio]
    video, audio = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    assert video.edits[0].media_time == 1024
    assert audio.edits == (Edit(500, -1), Edit(999, 0))
    assert audio.samples[0].dts == 0


def test_an_edit_list_keeps_tracks_in_sync_past_the_first_fragment() -> None:
    # The video's elst media_time (512) matches the composition delay (cto) of its own first
    # sample -- a B-frame reorder offset the source meant to cancel. This fragment starts well
    # after that media_time, so convert_edits rightly clamps the in-track trim to 0 (see its
    # docstring), but the leftover shift must still move with the track so it stays aligned with
    # the audio, which carries no edit list at all.
    delayed_video = Track(edits=((0, 512),))
    video = BytesSource(
        fragmented_file(
            [delayed_video], [[Traf(1, (Run((Sample(512, 100, cto=512),)),), tfdt=128_000)]]
        )
    )
    audio = BytesSource(
        fragmented_file([AUDIO], [[Traf(1, (Run((Sample(1024, 100),)),), tfdt=441_000)]])
    )
    video_track, audio_track = check_file(
        plan_mux([video, audio], flavor="mp4"), [video, audio]
    ).tracks
    assert _presentation_start(video_track) == _presentation_start(audio_track)


def _presentation_start(track: ParsedTrack) -> Fraction:
    lead = Fraction(0)
    if track.edits and track.edits[0].media_time == -1:
        lead = Fraction(track.edits[0].duration, 1000)
    sample = track.samples[0]
    return lead + Fraction(sample.dts + sample.cto, track.timescale)


def test_streams_are_rebased_to_start_at_zero() -> None:
    start = 2**33
    fragment = [Traf(1, (Run(tuple(video_samples(1))),), tfdt=start, tfdt_version=1)]
    sources = [BytesSource(fragmented_file([Track()], [fragment]))]
    (video,) = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    assert video.samples[0].dts == 0
    assert video.edits == ()


def test_m4a_holds_audio_only() -> None:
    sources = [audio_file()]
    parsed = check_file(plan_mux(sources, flavor="m4a"), sources)
    assert (parsed.major_brand, parsed.compatible_brands) == (
        "M4A ",
        ("M4A ", "isom", "iso2", "mp41"),
    )
    assert [track.handler for track in parsed.tracks] == ["soun"]
    with pytest.raises(MuxError, match="holds only audio"):
        plan_mux([video_file(), audio_file()], flavor="m4a")


def test_contiguous_samples_are_copied_with_one_operation_per_fragment() -> None:
    plan = plan_mux([audio_file()], flavor="m4a")
    assert isinstance(plan.ops[0], Blob)
    assert [type(op) for op in plan.ops[1:]] == [CopyOp, CopyOp, CopyOp]


def test_mov_rewrites_the_audio_description_and_names_handlers_in_pascal() -> None:
    sources = [video_file(), audio_file()]
    parsed = check_file(plan_mux(sources, flavor="mov"), sources)
    assert (parsed.major_brand, parsed.compatible_brands) == ("qt  ", ("qt  ",))
    video, audio = parsed.tracks
    assert (video.handler_name, audio.handler_name) == ("VideoHandler", "SoundHandler")
    assert video.data_handler
    assert audio.data_handler
    entry = Reader(audio.sample_entries[0], "mp4a")
    entry.skip(16)
    assert entry.u16() == 1  # SoundDescription version 1
    assert [kind for kind, _ in child_boxes(audio.sample_entries[0][52:], context="mp4a")] == [
        "wave"
    ]
    assert video.sample_entries == index_fragments(sources[0])[0].header.sample_entries


def test_mov_refuses_av1() -> None:
    with pytest.raises(MuxError, match="cannot hold AV1") as caught:
        plan_mux([video_file(track=Track(codec="av01"))], flavor="mov")
    assert ".mp4" in caught.value.suggestion


@pytest.mark.parametrize(
    "track",
    [
        Track(codec="hvc1"),
        Track(codec="encv"),  # encrypted (DRM) video
        Track(handler="soun", codec="Opus"),
        Track(handler="text", codec="tx3g"),
    ],
)
def test_unsupported_tracks_are_refused(track: Track) -> None:
    with pytest.raises(MuxError, match="audio can be muxed"):
        plan_mux([BytesSource(simple_file([Sample(512, 10)], track=track))], flavor="mp4")


def test_unknown_flavors_and_missing_inputs_are_refused() -> None:
    with pytest.raises(MuxError, match="Unknown container flavor"):
        plan_mux([audio_file()], flavor="webm")  # type: ignore[arg-type]
    with pytest.raises(MuxError, match="no input streams"):
        plan_mux([], flavor="mp4")


def test_the_same_inputs_always_give_the_same_bytes() -> None:
    sources = [video_file(), audio_file()]
    first, second = plan_mux(sources, flavor="mp4"), plan_mux(sources, flavor="mp4")
    assert first == second
    assert PlanSource(first, sources).read(0, first.size) == PlanSource(second, sources).read(
        0, second.size
    )


def test_description_changes_start_new_chunks() -> None:
    track = Track(entries=2)
    fragments = [
        [Traf(1, (Run(tuple(video_samples(1)[:10])),), flags=0x020002, description=1)],
        [Traf(1, (Run(tuple(video_samples(1)[10:])),), flags=0x020002, description=2, tfdt=5120)],
    ]
    sources = [BytesSource(fragmented_file([track], fragments))]
    (video,) = check_file(plan_mux(sources, flavor="mp4"), sources).tracks
    assert [chunk.description for chunk in video.chunks] == [1, 2]
    assert len(video.sample_entries) == 2


def test_plan_sources_read_across_operations() -> None:
    plan = MuxPlan((Blob(b"ab"), CopyOp(0, 2, 3), Blob(b"z")))
    source = PlanSource(plan, [BytesSource(b"0123456")])
    assert (plan.size, source.size) == (6, 6)
    assert source.read(0, 6) == b"ab234z"
    assert source.read(1, 3) == b"b23"
    assert source.read(5, 10) == b"z"
    assert source.read(6, 1) == b""


@pytest.mark.parametrize(
    ("itags", "flavor", "brands"),
    [
        ((137, 140), "mp4", ("isom", "iso2", "avc1", "mp41")),
        ((399, 140), "mp4", ("isom", "iso2", "av01", "mp41")),
        ((137, 140), "mov", ("qt  ",)),
        ((140,), "m4a", ("M4A ", "isom", "iso2", "mp41")),
    ],
)
def test_youtube_streams_mux_cleanly(
    itags: tuple[int, ...], flavor: str, brands: tuple[str, ...]
) -> None:
    sources = [HollowSource.load(itag) for itag in itags]
    parsed = check_file(plan_mux(sources, flavor=flavor), sources)  # type: ignore[arg-type]
    assert parsed.compatible_brands == brands
    if itags[0] == 137:
        (edit,) = parsed.tracks[0].edits
        assert edit.media_time == 512


@pytest.mark.parametrize(
    ("edits", "kwargs", "expected"),
    [
        ((), {}, ()),
        (((0, 1024),), {}, (Edit(3000, 1024),)),
        (((1_000_000, 1024),), {}, (Edit(3000, 1024),)),
        (((1500, 1024),), {}, (Edit(1500, 1024),)),
        (((250, -1), (0, 0)), {}, (Edit(250, -1), Edit(3080, 0))),
        (((0, 5000),), {"first_dts": 4000}, (Edit(3002, 1000),)),
        (((0, 100),), {"first_dts": 4000}, (Edit(3080, 0),)),
        (((0, 50_000),), {}, ()),
        ((), {"lead": Fraction(1, 2)}, (Edit(500, -1), Edit(3080, 0))),
        (((0, 1024),), {"lead": Fraction(2, 3)}, (Edit(666, -1), Edit(3000, 1024))),
    ],
)
def test_convert_edits(
    edits: tuple[tuple[int, int], ...], kwargs: dict[str, object], expected: tuple[Edit, ...]
) -> None:
    arguments: dict[str, object] = {
        "movie_timescale": 1000,
        "timescale": 12800,
        "first_dts": 0,
        "presentation_end": 39424,  # 3.08 s
        "lead": Fraction(0),
    }
    arguments.update(kwargs)
    source = tuple(Edit(duration, media_time) for duration, media_time in edits)
    assert convert_edits(source, **arguments) == expected  # type: ignore[arg-type]


def test_empty_samples_are_listed_but_copy_nothing() -> None:
    samples = [Sample(512, 100), Sample(512, 0, sync=False), Sample(512, 100, sync=False)]
    sources = [BytesSource(simple_file(samples))]
    plan = plan_mux(sources, flavor="mp4")
    (video,) = check_file(plan, sources).tracks
    assert [sample.size for sample in video.samples] == [100, 0, 100]
    assert sum(isinstance(op, CopyOp) for op in plan.ops) == 1


def test_a_track_that_switches_to_an_unsupported_codec_is_refused() -> None:
    data = simple_file([Sample(512, 10)], track=Track(entries=2))
    second = data.index(b"avc1", data.index(b"avc1") + 4)
    mixed = data[:second] + b"hvc1" + data[second + 4 :]
    with pytest.raises(MuxError, match=r"'avc1\+hvc1'"):
        plan_mux([BytesSource(mixed)], flavor="mp4")


def test_a_track_that_mixes_avc1_and_av01_is_refused() -> None:
    # Both codecs map to the same TrackKind ("video"); the mix must still be refused.
    data = simple_file([Sample(512, 10)], track=Track(entries=2))
    second = data.index(b"avc1", data.index(b"avc1") + 4)
    mixed = data[:second] + b"av01" + data[second + 4 :]
    with pytest.raises(MuxError, match=r"'av01\+avc1'"):
        plan_mux([BytesSource(mixed)], flavor="mp4")
