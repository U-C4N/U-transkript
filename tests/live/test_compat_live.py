"""Live checks of utmax.compat (spec §4.6) on dQw4w9WgXcQ."""

from __future__ import annotations

import pytest

from utmax.compat import NoTranscriptFound, YouTubeTranscriptApi
from utmax.compat.formatters import SRTFormatter

pytestmark = pytest.mark.live

VIDEO = "dQw4w9WgXcQ"


def test_fetch_returns_the_manual_english_transcript() -> None:
    transcript = YouTubeTranscriptApi().fetch(VIDEO)

    assert (transcript.video_id, transcript.language_code, transcript.is_generated) == (
        VIDEO,
        "en",
        False,
    )
    assert transcript.language == "English"
    assert transcript[1].text == "♪ We're no strangers to love ♪"
    assert transcript[1].start == 18.64
    assert transcript[2].text == "♪ You know the rules\nand so do I ♪"
    assert (
        SRTFormatter()
        .format_transcript(transcript)
        .startswith("1\n00:00:01,360 --> 00:00:03,040\n")
    )


def test_list_offers_manual_generated_and_translation_languages() -> None:
    transcript_list = YouTubeTranscriptApi().list(f"https://youtu.be/{VIDEO}")

    codes = [(t.language_code, t.is_generated) for t in transcript_list]
    assert ("en", False) in codes
    assert ("en", True) in codes
    english = transcript_list.find_generated_transcript(["en"])
    assert english.is_translatable
    assert "tr" in {language.language_code for language in english.translation_languages}
    with pytest.raises(NoTranscriptFound):
        transcript_list.find_transcript(["de"])
    assert transcript_list.find_transcript(["de-DE"]).language == "German (Germany)"


def test_the_class_methods_of_version_0_6_return_dictionaries() -> None:
    with pytest.deprecated_call():
        raw = YouTubeTranscriptApi.get_transcript(VIDEO, languages=["de", "en"])

    assert raw[1] == {
        "text": "♪ We're no strangers to love ♪",
        "start": 18.64,
        "duration": 3.24,
    }
