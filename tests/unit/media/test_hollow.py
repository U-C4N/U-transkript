"""YouTube's real stream structure (hollow fixtures) through the indexer."""

from __future__ import annotations

import pytest

from tests.helpers.hollow_source import MEDIA, HollowSource, manifest, stream_facts
from utmax.core.media.fmp4 import index_fragments


def test_the_recording_shows_the_stream_layout_the_spec_describes() -> None:
    video, audio, av1 = stream_facts(137), stream_facts(140), stream_facts(399)
    assert manifest()["video_id"] == "dQw4w9WgXcQ"
    assert video["elst_media_time"] == 512
    assert {fragment["tfhd_flags"] for fragment in video["fragments"]} == {0x02000A}
    assert {fragment["trun_flags"] for fragment in video["fragments"]} == {0x000E01}
    assert {fragment["tfhd_flags"] for fragment in audio["fragments"]} == {0x02002A}
    assert {fragment["trun_flags"] for fragment in audio["fragments"]} == {0x000201}
    assert {fragment["trun_flags"] for fragment in av1["fragments"]} == {0x000601}


@pytest.mark.parametrize(
    ("itag", "codec", "handler"),
    [(137, "avc1", "vide"), (140, "mp4a", "soun"), (399, "av01", "vide")],
)
def test_hollow_streams_index_as_the_manifest_says(itag: int, codec: str, handler: str) -> None:
    facts = stream_facts(itag)
    source = HollowSource.load(itag)
    assert source.size == facts["virtual_size"]
    (track,) = index_fragments(source)
    header, samples = track.header, track.samples
    assert (header.codec, header.handler, header.timescale) == (codec, handler, facts["timescale"])
    assert len(samples) == sum(fragment["samples"] for fragment in facts["fragments"])
    assert sum(samples.sizes) == sum(fragment["mdat_payload"] for fragment in facts["fragments"])
    assert samples.offsets[-1] + samples.sizes[-1] <= source.size
    media_time = facts["elst_media_time"]
    assert [edit.media_time for edit in header.edits] == (
        [] if media_time is None else [media_time]
    )


@pytest.mark.parametrize("itag", [137, 399])
def test_every_video_fragment_starts_with_a_sync_sample(itag: int) -> None:
    (track,) = index_fragments(HollowSource.load(itag))
    first = 0
    for fragment in stream_facts(itag)["fragments"]:
        assert track.samples.sync[first] == 1
        first += fragment["samples"]
    assert 0 < sum(track.samples.sync) < len(track.samples)


def test_hollow_sources_read_zeros_inside_mdat_payloads() -> None:
    source = HollowSource.load(140)
    (track,) = index_fragments(source)
    assert source.read(track.samples.offsets[0], 16) == bytes(16)
    assert source.read(0, 8)[4:] == b"ftyp"
    assert source.read(source.size, 4) == b""


def test_fixtures_store_no_stream_urls() -> None:
    for path in MEDIA.iterdir():
        data = path.read_bytes()
        for secret in (b"http", b"googlevideo", b"signature", b"lsig="):
            assert secret not in data, (path.name, secret)
