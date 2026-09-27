"""Tests for player-response parsing."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers.youtube import VIDEO_ID, player_payload
from utmax.core.player import CaptionTrackInfo, parse_player_response
from utmax.models import Language, VideoInfo


def test_video_details_become_video_info() -> None:
    player = parse_player_response(player_payload(), video_id=VIDEO_ID)
    assert player.video == VideoInfo(
        VIDEO_ID,
        "Rick Astley - Never Gonna Give You Up (Official Video)",
        "Rick Astley",
        "UCuAXFkgsw1L7xaCfnd5JJOw",
        213.0,
        False,
    )
    assert player.playability.status == "OK"


def test_caption_tracks_keep_youtube_order_and_kinds() -> None:
    player = parse_player_response(player_payload(), video_id=VIDEO_ID)
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
    assert tracks[1] == CaptionTrackInfo(
        base_url=f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=srv3&kind=asr",
        language_code="en",
        name="English (auto-generated)",
        is_generated=True,
        is_translatable=True,
        vss_id="a.en",
    )
    assert player.translation_languages == (Language("tr", "Turkish"), Language("de", "German"))


def test_names_fall_back_to_simple_text_then_the_code() -> None:
    data = player_payload()
    tracks = data["captions"]["playerCaptionsTracklistRenderer"]["captionTracks"]
    tracks[0]["name"] = {"simpleText": "English (simple)"}
    del tracks[2]["name"]
    parsed = parse_player_response(data, video_id=VIDEO_ID).caption_tracks or ()
    assert (parsed[0].name, parsed[2].name) == ("English (simple)", "de-DE")


@pytest.mark.parametrize(
    "captions",
    [
        None,
        {},
        {"playerCaptionsTracklistRenderer": {"captionTracks": []}},
        {"playerCaptionsTracklistRenderer": {"captionTracks": [{"languageCode": "en"}]}},
        ["not", "an", "object"],
    ],
)
def test_missing_or_unusable_captions_mean_none(captions: Any) -> None:
    data = player_payload(captions=False)
    if captions is not None:
        data["captions"] = captions
    player = parse_player_response(data, video_id=VIDEO_ID)
    assert player.caption_tracks is None
    assert player.translation_languages == ()


def test_malformed_video_details_fall_back_to_defaults() -> None:
    player = parse_player_response({"videoDetails": {"lengthSeconds": "soon"}}, video_id=VIDEO_ID)
    assert player.video == VideoInfo(VIDEO_ID, "", "", "", 0.0, False)
    assert (
        parse_player_response({"videoDetails": "odd"}, video_id=VIDEO_ID).video.video_id == VIDEO_ID
    )
