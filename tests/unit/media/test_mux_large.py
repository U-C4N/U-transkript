"""Files above 4 GiB: co64 and a 64-bit mdat size exactly when needed, checked without writing."""

from __future__ import annotations

from tests.helpers.fmp4_factory import Run, Sample, Track, Traf, VirtualSource, virtual_file
from tests.unit.media.invariants import check_file
from utmax.core.media.boxes import U32_MAX
from utmax.core.media.fmp4 import index_fragments
from utmax.core.media.mux import PlanSource, plan_mux

VIDEO = Track(timescale=1000)
AUDIO = Track(handler="soun", codec="mp4a", timescale=1000)
FRAME = 90_000_000  # one 90 MB "sample" per second: 60 s = 5.4 GB


def stream(track: Track, samples: list[Sample], per_fragment: int = 10) -> VirtualSource:
    fragments = [
        [Traf(1, (Run(tuple(samples[i : i + per_fragment])),), tfdt=i * 1000)]
        for i in range(0, len(samples), per_fragment)
    ]
    return virtual_file([track], fragments)


def big_video(seconds: int = 60) -> VirtualSource:
    return stream(VIDEO, [Sample(1000, FRAME) for _ in range(seconds)])


def small_audio(seconds: int) -> VirtualSource:
    return stream(AUDIO, [Sample(1000, 1000) for _ in range(seconds)])


def test_every_track_that_reaches_past_4_gib_uses_co64() -> None:
    sources = [big_video(), small_audio(60)]
    plan = plan_mux(sources, flavor="mp4")
    assert plan.size > 5_000_000_000
    parsed = check_file(plan, sources, hash_payloads=False)
    assert parsed.boxes[2].header_size == 16
    assert [track.chunk_box for track in parsed.tracks] == ["co64", "co64"]


def test_a_track_that_ends_early_keeps_32_bit_offsets() -> None:
    sources = [big_video(), small_audio(10)]
    parsed = check_file(plan_mux(sources, flavor="mp4"), sources, hash_payloads=False)
    assert [track.chunk_box for track in parsed.tracks] == ["co64", "stco"]
    assert max(chunk.offset for chunk in parsed.tracks[1].chunks) < U32_MAX


def test_a_huge_first_chunk_needs_only_the_64_bit_mdat_size() -> None:
    samples = [Sample(400, 3_900_000_000), Sample(400, 400_000_000)]
    sources = [stream(VIDEO, samples)]
    parsed = check_file(plan_mux(sources, flavor="mp4"), sources, hash_payloads=False)
    assert parsed.boxes[2].header_size == 16
    assert parsed.boxes[2].size > U32_MAX
    assert parsed.tracks[0].chunk_box == "stco"


def test_samples_beyond_4_gib_are_copied_from_the_right_place() -> None:
    sources = [big_video(), small_audio(60)]
    plan = plan_mux(sources, flavor="mp4")
    output = PlanSource(plan, sources)
    parsed = check_file(plan, sources, hash_payloads=False)
    for number, (track, expected) in enumerate(
        zip(parsed.tracks, [index_fragments(source)[0] for source in sources], strict=True)
    ):
        for index in (0, len(track.samples) - 1):
            sample, offset = track.samples[index], expected.samples.offsets[index]
            assert output.read(sample.offset, 64) == sources[number].read(offset, 64)
            end = sample.offset + sample.size
            assert output.read(end - 64, 64) == sources[number].read(offset + sample.size - 64, 64)
