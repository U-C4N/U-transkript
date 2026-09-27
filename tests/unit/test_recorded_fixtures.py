"""Offline tests over real, redacted YouTube responses (see scripts/record_fixtures.py)."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from tests.helpers.fake_transport import FakeTransport, json_response
from utmax import Client
from utmax.core.captions import parse_json3, parse_xml
from utmax.core.player import parse_player_response
from utmax.core.segmentation import merge_sentences

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "youtube"
VIDEO_ID = "dQw4w9WgXcQ"
SECOND_LINE = "♪ We're no strangers to love ♪"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name", ["player_android.json", "player_ios.json", "player_android_vr.json"]
)
def test_every_profile_lists_the_same_six_tracks(name: str) -> None:
    player = parse_player_response(load(name), video_id=VIDEO_ID)
    assert player.playability.status == "OK"
    assert "Never Gonna Give You Up" in player.video.title
    assert player.video.channel == "Rick Astley"
    tracks = player.caption_tracks or ()
    assert [track.language_code for track in tracks] == [
        "en",
        "en",
        "de-DE",
        "ja",
        "pt-BR",
        "es-419",
    ]
    assert [track.is_generated for track in tracks] == [False, True, False, False, False, False]
    assert all("REDACTED" in track.base_url for track in tracks)


def test_only_android_and_ios_list_translation_languages() -> None:
    assert parse_player_response(
        load("player_android.json"), video_id=VIDEO_ID
    ).translation_languages
    assert parse_player_response(load("player_ios.json"), video_id=VIDEO_ID).translation_languages
    assert (
        parse_player_response(
            load("player_android_vr.json"), video_id=VIDEO_ID
        ).translation_languages
        == ()
    )


def test_manual_json3() -> None:
    segments = parse_json3(load("json3_en_manual.json"), is_generated=False)
    assert segments[1].text == SECOND_LINE
    assert (segments[1].start, segments[1].duration) == (18.64, 3.24)
    assert "\n" in segments[2].text
    assert all(not segment.words for segment in segments)


def test_auto_json3_has_words_and_merges_cleanly() -> None:
    segments = parse_json3(load("json3_en_asr.json"), is_generated=True)
    assert segments[0].text == "[Music]"
    assert all(segment.text and segment.words for segment in segments)
    merged = merge_sentences(segments)
    assert merged
    assert all(segment.text for segment in merged)
    for current, following in pairwise(merged):
        assert current.start <= following.start
        assert current.end <= following.start + 1e-9


def test_legacy_and_srv3_xml() -> None:
    legacy = parse_xml(
        (FIXTURES / "legacy_en_manual.xml").read_text(encoding="utf-8"), is_generated=False
    )
    assert legacy[1].text == SECOND_LINE
    srv3 = parse_xml((FIXTURES / "srv3_en_asr.xml").read_text(encoding="utf-8"), is_generated=True)
    assert srv3[0].text == "[Music]"
    assert any(len(segment.words) > 1 for segment in srv3)


def test_end_to_end_over_recorded_responses() -> None:
    transport = FakeTransport()
    transport.add("POST", "/youtubei/v1/player", json_response(load("player_android.json")))
    transport.add("GET", "/api/timedtext", json_response(load("json3_en_manual.json")))
    transcript = Client(transport=transport).fetch(f"https://youtu.be/{VIDEO_ID}")
    assert (transcript.language_code, transcript.is_generated) == ("en", False)
    assert transcript.segments[1].text == SECOND_LINE
