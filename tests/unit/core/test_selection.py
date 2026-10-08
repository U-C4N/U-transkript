"""Tests for select_track."""

from __future__ import annotations

import pytest

from tests.helpers.builders import VIDEO, make_track
from utmax.core.selection import describe_track, select_track
from utmax.errors import NoTranscriptFound
from utmax.models import Track, TrackList

EN = make_track("en", name="English")
EN_AUTO = make_track("en", generated=True, name="English (auto-generated)")
DE = make_track("de-DE", name="German (Germany)")
JA = make_track("ja", name="Japanese")
RICK = (EN, EN_AUTO, DE, JA)


def pick(tracks: tuple[Track, ...], languages: object = None, **flags: bool) -> Track:
    return select_track(tracks, languages, **flags)  # type: ignore[arg-type]


def test_manual_beats_auto_for_the_same_code() -> None:
    assert pick(RICK, ["en"]) is EN


def test_requested_languages_are_tried_in_order() -> None:
    assert pick(RICK, ["tr", "ja", "en"]) is JA


def test_base_language_matches_regional_tracks() -> None:
    assert pick(RICK, ["de"]) is DE
    assert pick((make_track("de"),), ["de-AT"]).language_code == "de"


def test_a_regional_manual_track_beats_an_exact_auto_track() -> None:
    en_gb = make_track("en-GB")
    assert pick((en_gb, EN_AUTO), ["en"]) is en_gb


def test_exact_codes_win_within_the_same_kind() -> None:
    assert pick((make_track("en-GB"), EN), ["en"]) is EN
    en_gb_auto = make_track("en-GB", generated=True)
    assert pick((en_gb_auto, EN_AUTO), ["en"]) is EN_AUTO


def test_codes_are_case_insensitive_and_a_bare_string_is_one_code() -> None:
    assert pick(RICK, ["EN"]) is EN
    assert pick(RICK, "ja") is JA


def test_filters() -> None:
    assert pick(RICK, ["en"], include_manual=False) is EN_AUTO
    assert pick(RICK, ["en"], include_generated=False) is EN


def test_default_prefers_the_spoken_language_manual_track() -> None:
    assert pick((DE, EN_AUTO, EN)) is EN
    assert pick((DE, make_track("en-GB"), EN_AUTO)).language_code == "en-GB"


def test_default_falls_back_to_spoken_auto_then_first_manual_then_first_auto() -> None:
    assert pick((DE, EN_AUTO)) is EN_AUTO
    assert pick((JA, DE)) is JA
    assert pick((EN_AUTO,), include_generated=True) is EN_AUTO
    assert pick((DE, EN_AUTO), include_generated=False) is DE


def test_missing_languages_list_what_is_available() -> None:
    with pytest.raises(NoTranscriptFound) as caught:
        pick(RICK, ["tr", "ko"])
    error = caught.value
    assert error.requested == ("tr", "ko")
    assert error.available == tuple(describe_track(track) for track in RICK)
    assert "de-DE (German (Germany), manual)" in str(error)
    assert "en (English (auto-generated), auto-generated)" in str(error)
    assert error.video_id == VIDEO.video_id


def test_filters_that_exclude_everything_raise() -> None:
    with pytest.raises(NoTranscriptFound):
        pick((EN,), include_manual=False)
    with pytest.raises(NoTranscriptFound):
        pick(())


def test_track_list_find_uses_the_same_rules() -> None:
    tracks = TrackList(video=VIDEO, tracks=RICK)
    assert tracks.find(["de"]) is DE
    assert tracks.find() is EN
    assert tracks.find(["en"], include_manual=False) is EN_AUTO


AR_AUTO = make_track("ar", generated=True, name="Arabic (auto-generated)")
DUBBED = (AR_AUTO, EN, EN_AUTO, make_track("de", generated=True))


def test_the_original_audio_language_beats_tracks_of_dubbed_audio() -> None:
    """Videos with dubbed audio list an auto-generated track per dub, often before the
    original's; without the original audio's language the first one would win."""
    assert pick(DUBBED) is AR_AUTO
    assert select_track(DUBBED, spoken_language="en-US") is EN
    assert select_track(DUBBED, spoken_language="en-US", include_manual=False) is EN_AUTO
    assert select_track(DUBBED, ["ar"], spoken_language="en-US") is AR_AUTO


def test_a_spoken_language_without_tracks_falls_back_to_the_first_auto_track() -> None:
    assert select_track((AR_AUTO, DE), spoken_language="fr") is AR_AUTO
    assert select_track((JA, DE), spoken_language="fr") is JA


def test_track_list_find_uses_the_original_audio_language() -> None:
    tracks = TrackList(video=VIDEO, tracks=DUBBED, spoken_language="en-US")
    assert tracks.find() is EN
    assert tracks.find(include_manual=False) is EN_AUTO
    assert TrackList(video=VIDEO, tracks=DUBBED).find() is AR_AUTO
