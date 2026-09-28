"""Tests for the transcript service (InnerTube faked, everything else real)."""

from __future__ import annotations

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response
from tests.helpers.youtube import (
    ASR_JSON3,
    VIDEO_ID,
    json3_payload,
    player_payload,
    standard_youtube,
)
from utmax.adapters.innertube import InnerTubeClient
from utmax.errors import InvalidVideoId, NoTranscriptFound, TranscriptsDisabled
from utmax.services.transcripts import TranscriptService


def service(transport: FakeTransport) -> TranscriptService:
    return TranscriptService(InnerTubeClient(transport))


def test_list_tracks_returns_bound_tracks_in_youtube_order() -> None:
    tracks = service(standard_youtube()).list_tracks(f"https://youtu.be/{VIDEO_ID}")
    assert [track.language_code for track in tracks] == [
        "en",
        "en",
        "de-DE",
        "ja",
        "pt-BR",
        "es-419",
    ]
    assert tracks.video.title.startswith("Rick Astley")
    assert [language.code for language in tracks.translation_languages] == ["tr", "de"]
    assert tracks[0].fetch().segments[1].text == "♪ We're no strangers to love ♪"


def test_fetch_defaults_to_the_spoken_language_manual_track() -> None:
    transport = standard_youtube()
    transcript = service(transport).fetch(VIDEO_ID)
    assert (transcript.language_code, transcript.language, transcript.is_generated) == (
        "en",
        "English",
        False,
    )
    assert transcript.segments[1].text == "♪ We're no strangers to love ♪"
    assert transcript.translated_from is None
    assert transport.urls("GET") == [
        f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=json3"
    ]


def test_base_language_match() -> None:
    transcript = service(standard_youtube()).fetch(VIDEO_ID, languages=["de"])
    assert (transcript.language_code, transcript.text) == ("de-DE", "Wir sind keine Fremden")


def test_language_order_never_falls_back_to_youtube_translation() -> None:
    transport = standard_youtube()
    assert service(transport).fetch(VIDEO_ID, languages=["tr", "en"]).language_code == "en"
    assert not any("tlang=" in url for url in transport.urls())


def test_explicit_youtube_translation_is_marked() -> None:
    transport = standard_youtube()
    transport.add(
        "GET", "tlang=tr", json_response(json3_payload((18640, 3240, "Aşka yabancı değiliz")))
    )
    transcript = service(transport).fetch(VIDEO_ID, youtube_translation="tr")
    assert (transcript.language_code, transcript.language) == ("tr", "Turkish")
    assert (transcript.translated_from, transcript.translator) == ("en", "youtube")
    assert transcript.text == "Aşka yabancı değiliz"


def test_videos_with_only_auto_captions_use_them() -> None:
    transport = FakeTransport()
    only_auto = (("en", "English (auto-generated)", True),)
    transport.add("POST", "/player", json_response(player_payload(tracks=only_auto)))
    transport.add("GET", "kind=asr", json_response(ASR_JSON3))
    transcript = service(transport).fetch(VIDEO_ID)
    assert transcript.is_generated
    assert transcript.segments[0].text == "[Music]"
    assert transcript.segments[1].words


def test_missing_languages_list_what_is_available() -> None:
    with pytest.raises(NoTranscriptFound) as caught:
        service(standard_youtube()).fetch(VIDEO_ID, languages="ko")
    assert caught.value.requested == ("ko",)
    assert "de-DE (German (Germany), manual)" in str(caught.value)


def test_videos_without_captions_raise_transcripts_disabled() -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", json_response(player_payload(captions=False)))
    with pytest.raises(TranscriptsDisabled) as caught:
        service(transport).fetch(VIDEO_ID)
    assert caught.value.video_id == VIDEO_ID


def test_video_info_works_without_captions() -> None:
    transport = FakeTransport()
    transport.add("POST", "/player", json_response(player_payload(captions=False)))
    info = service(transport).video_info(f"https://www.youtube.com/watch?v={VIDEO_ID}")
    assert (info.video_id, info.channel, info.duration) == (VIDEO_ID, "Rick Astley", 213.0)


def test_invalid_input_never_reaches_the_network() -> None:
    transport = FakeTransport()
    with pytest.raises(InvalidVideoId):
        service(transport).fetch("not a video")
    assert transport.requests == []


def test_preserve_formatting_reaches_the_parser() -> None:
    styled = {
        "pens": [{}, {"iAttr": 1}],
        "events": [
            {
                "tStartMs": 0,
                "dDurationMs": 900,
                "segs": [{"utf8": "so "}, {"utf8": "cool", "pPenId": 1}],
            }
        ],
    }
    transport = FakeTransport()
    transport.add("POST", "/player", json_response(player_payload()))
    transport.add("GET", "lang=en&fmt=json3", json_response(styled))
    transcript = service(transport).fetch(VIDEO_ID, preserve_formatting=True)
    assert transcript.text == "so <i>cool</i>"


def test_track_list_reuses_a_player_response_without_another_request() -> None:
    transport = standard_youtube()
    innertube = InnerTubeClient(transport)
    tracks = TranscriptService(innertube).track_list(innertube.player(VIDEO_ID))
    assert len(tracks) == 6
    assert len(transport.urls("POST")) == 1
    assert tracks[0].fetch().language_code == "en"


def test_track_list_is_empty_without_captions() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(player_payload(captions=False)))
    innertube = InnerTubeClient(transport)
    assert len(TranscriptService(innertube).track_list(innertube.player(VIDEO_ID))) == 0
