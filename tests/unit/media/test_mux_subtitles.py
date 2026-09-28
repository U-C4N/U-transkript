"""Tests for embedding transcripts as tx3g subtitle tracks."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.helpers.builders import make_transcript
from tests.helpers.fmp4_factory import Sample, Track, simple_file
from tests.helpers.hollow_source import HollowSource
from tests.unit.media.invariants import check_file
from utmax.core.media.boxes import BytesSource
from utmax.core.media.moov import pack_language
from utmax.core.media.mux import PlanSource, plan_mux
from utmax.core.media.progressive import Track as ParsedTrack
from utmax.core.media.tx3g import Cue, decode_sample, normalize_cues, sample_entry
from utmax.errors import InvalidOption, MuxError
from utmax.models import Segment, Transcript

ENGLISH = make_transcript(Segment(0.5, 1.0, "Hello"), Segment(2.0, 0.8, "World\nline two"))
TURKISH = replace(
    make_transcript(
        Segment(0.5, 1.0, "Merhaba"),
        Segment(2.0, 0.8, "D\xfcnya"),
        language_code="tr",
        language="Turkish",
        is_generated=True,
    ),
    translated_from="en",
    translator="claude=claude-opus-5",
)
BILINGUAL = make_transcript(
    Segment(0.5, 1.0, "Hello\nMerhaba"), language_code="en+tr", language="English + Turkish"
)


def media(seconds: int = 3) -> list[BytesSource]:
    video = [Sample(512, 500, sync=i % 25 == 0, cto=1024) for i in range(25 * seconds)]
    audio = [Sample(1024, 200) for _ in range(43 * seconds)]
    audio_track = Track(handler="soun", codec="mp4a", timescale=44100)
    return [
        BytesSource(simple_file(video, per_fragment=25)),
        BytesSource(simple_file(audio, track=audio_track, per_fragment=43)),
    ]


def cues_of(track: ParsedTrack, output: PlanSource) -> list[Cue]:
    cues = []
    for sample in track.samples:
        text = decode_sample(output.read(sample.offset, sample.size))
        if text:
            cues.append(Cue(sample.dts, sample.dts + sample.duration, text))
    return cues


def mux(transcripts: list[Transcript], **options: str) -> tuple[list[ParsedTrack], PlanSource]:
    sources = media()
    plan = plan_mux(sources, flavor=options.pop("flavor", "mp4"), subtitles=transcripts, **options)  # type: ignore[arg-type]
    parsed = check_file(plan, sources)
    return list(parsed.tracks[2:]), PlanSource(plan, sources)


def test_subtitles_follow_the_media_as_tx3g_tracks() -> None:
    tracks, _ = mux([ENGLISH, TURKISH, BILINGUAL])
    assert [track.track_id for track in tracks] == [3, 4, 5]
    assert {(t.handler, t.media_header, t.alternate_group, t.timescale) for t in tracks} == {
        ("sbtl", "nmhd", 3, 1000)
    }
    assert all(track.sample_entries == (sample_entry(),) for track in tracks)
    assert [track.handler_name for track in tracks] == [
        "English",
        "Turkish (AI: claude=claude-opus-5)",
        "English + Turkish",
    ]
    assert [track.name for track in tracks] == [track.handler_name for track in tracks]
    assert [track.extended_language for track in tracks] == ["en", "tr", "mul"]
    assert [track.language for track in tracks] == [
        pack_language("eng"),
        pack_language("tur"),
        pack_language("mul"),
    ]


def test_exactly_one_subtitle_track_is_enabled() -> None:
    assert [t.flags for t in mux([ENGLISH, TURKISH, BILINGUAL])[0]] == [3, 2, 2]
    assert [t.flags for t in mux([ENGLISH, TURKISH], default_subtitle="tr")[0]] == [2, 3]
    both = mux([ENGLISH, TURKISH, BILINGUAL], default_subtitle="EN+TR")[0]
    assert [t.flags for t in both] == [2, 2, 3]


def test_an_unknown_default_subtitle_fails_before_the_inputs_are_read() -> None:
    with pytest.raises(InvalidOption, match="default_subtitle='de'"):
        plan_mux(
            [BytesSource(b"not an mp4")], flavor="mp4", subtitles=[ENGLISH], default_subtitle="de"
        )


def test_m4a_cannot_carry_subtitles() -> None:
    with pytest.raises(MuxError, match="cannot hold subtitle tracks"):
        plan_mux(media()[1:], flavor="m4a", subtitles=[ENGLISH])


def test_subtitle_text_and_timing_round_trip() -> None:
    tracks, output = mux([ENGLISH, TURKISH])
    assert cues_of(tracks[0], output) == list(normalize_cues(ENGLISH.segments))
    assert cues_of(tracks[1], output) == list(normalize_cues(TURKISH.segments))
    assert [sample.duration for sample in tracks[0].samples] == [500, 1000, 500, 800, 280]


def test_the_last_cue_is_followed_by_an_empty_sample_until_the_media_ends() -> None:
    # FFmpeg before 7 stretches a track's last sample to the end of the file; the empty
    # sample takes that stretch, so "World" still disappears at 2.8 s in every player.
    (track,), output = mux([ENGLISH])
    last = track.samples[-1]
    assert decode_sample(output.read(last.offset, last.size)) == ""
    assert (last.dts, last.dts + last.duration) == (2800, 3080)
    assert track.duration == 3080


def test_subtitles_end_with_the_media() -> None:
    late = make_transcript(
        Segment(2.5, 3.0, "runs past the end"), Segment(10.0, 1.0, "after the end")
    )
    (track,), output = mux([late])
    assert cues_of(track, output) == [Cue(2500, 3080, "runs past the end")]
    assert track.duration == 3080


def test_a_transcript_without_cues_still_gets_a_track() -> None:
    (track,), output = mux([make_transcript()])
    assert [
        (sample.duration, decode_sample(output.read(sample.offset, sample.size)))
        for sample in track.samples
    ] == [(3080, "")]


def test_subtitle_chunks_hold_up_to_ten_seconds() -> None:
    every_second = make_transcript(*(Segment(float(s), 0.5, f"cue {s}") for s in range(25)))
    sources = media(25)
    parsed = check_file(plan_mux(sources, flavor="mp4", subtitles=[every_second]), sources)
    assert len(parsed.tracks[2].chunks) == 3


def test_mov_subtitles_use_quicktime_language_codes() -> None:
    traditional = make_transcript(Segment(0, 1, "x"), language_code="zh-Hant", language="Chinese")
    filipino = make_transcript(Segment(0, 1, "x"), language_code="fil", language="Filipino")
    tracks, _ = mux([TURKISH, traditional, filipino], flavor="mov")
    assert [track.language for track in tracks] == [17, 19, pack_language("fil")]
    assert [track.handler_name for track in tracks][1:] == ["Chinese", "Filipino"]
    assert all(track.data_handler for track in tracks)


def test_youtube_streams_with_subtitles() -> None:
    sources = [HollowSource.load(137), HollowSource.load(140)]
    plan = plan_mux(sources, flavor="mp4", subtitles=[ENGLISH, TURKISH], default_subtitle="tr")
    parsed = check_file(plan, sources)
    assert [track.handler for track in parsed.tracks] == ["vide", "soun", "sbtl", "sbtl"]
    assert [track.flags for track in parsed.tracks] == [3, 3, 2, 3]
