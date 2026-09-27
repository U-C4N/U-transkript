"""Tests for the shared data types."""

from __future__ import annotations

import dataclasses

import pytest

from tests.helpers.builders import VIDEO, make_track, make_transcript
from utmax.models import Segment, Track, TrackList, Transcript, Word


def test_segment_end_and_video_url() -> None:
    assert Segment(1.5, 2.25, "hi").end == 3.75
    assert VIDEO.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_segments_can_carry_word_timings() -> None:
    segment = Segment(0.0, 1.0, "hello world", (Word("hello", 0.0), Word("world", 0.5)))
    assert [word.text for word in segment.words] == ["hello", "world"]


def test_models_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        VIDEO.title = "changed"  # type: ignore[misc]


def test_transcript_behaves_like_a_sequence_of_segments() -> None:
    first, second = Segment(0.0, 1.0, "a"), Segment(1.0, 1.0, "b")
    transcript = make_transcript(first, second)
    assert len(transcript) == 2
    assert transcript[0] is first
    assert transcript[-1] is second
    assert transcript[0:1] == (first,)
    assert list(transcript) == [first, second]
    assert second in transcript


def test_text_collapses_whitespace_and_skips_empty_segments() -> None:
    transcript = make_transcript(
        Segment(0, 1, "  hello\nworld "), Segment(1, 1, "   "), Segment(2, 1, "again")
    )
    assert transcript.text == "hello world again"


def test_is_bilingual_and_to_dicts() -> None:
    bilingual = make_transcript(Segment(0.0, 1.5, "hi"), language_code="en+tr")
    assert bilingual.is_bilingual
    assert not make_transcript().is_bilingual
    assert bilingual.to_dicts() == [{"text": "hi", "start": 0.0, "duration": 1.5}]


def test_transcript_equality_ignores_source() -> None:
    base = make_transcript(Segment(0, 1, "a"))
    with_source = dataclasses.replace(base, source=make_transcript(Segment(0, 1, "b")))
    assert base == with_source


class RecordingFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[Track, bool]] = []

    def fetch_track(self, track: Track, *, preserve_formatting: bool) -> Transcript:
        self.calls.append((track, preserve_formatting))
        return make_transcript(Segment(0, 1, "fetched"))


def test_track_fetch_delegates_to_its_fetcher() -> None:
    fetcher = RecordingFetcher()
    track = make_track("de-DE", fetcher=fetcher)
    assert track.fetch(preserve_formatting=True).text == "fetched"
    assert fetcher.calls == [(track, True)]
    assert track.video_id == "dQw4w9WgXcQ"


def test_unbound_track_cannot_fetch() -> None:
    with pytest.raises(RuntimeError, match="not bound"):
        make_track().fetch()


def test_track_equality_ignores_private_fields() -> None:
    assert make_track(url="https://a.example") == make_track(url="https://b.example")
    assert "https://" not in repr(make_track())


def test_track_list_is_a_sequence_with_filters() -> None:
    manual, auto = make_track("en"), make_track("en", generated=True)
    tracks = TrackList(video=VIDEO, tracks=(manual, auto))
    assert len(tracks) == 2
    assert tracks[1] is auto
    assert tracks[:1] == (manual,)
    assert list(tracks) == [manual, auto]
    assert tracks.manual == (manual,)
    assert tracks.generated == (auto,)
