"""Tests for YouTube's own track translation (tlang)."""

from __future__ import annotations

import pytest

from tests.helpers.builders import make_track
from utmax.errors import NotTranslatable, TranslationLanguageNotAvailable
from utmax.models import Language

LANGUAGES = (Language("tr", "Turkish"), Language("de", "German"))


def test_translate_adds_tlang_and_marks_the_track() -> None:
    track = make_track("en", name="English", translation_languages=LANGUAGES)
    translated = track.translate("tr")
    assert (translated.language_code, translated.language) == ("tr", "Turkish")
    assert translated.is_generated
    assert not translated.is_translatable
    assert translated.translation_of == "en"
    assert translated._url.endswith("&tlang=tr")
    assert translated.video == track.video


def test_unknown_translation_languages_are_rejected() -> None:
    with pytest.raises(TranslationLanguageNotAvailable) as caught:
        make_track(translation_languages=LANGUAGES).translate("ko")
    assert caught.value.available == ("tr", "de")


def test_without_a_language_list_translation_is_best_effort() -> None:
    assert make_track().translate("ko").language == "ko"


def test_untranslatable_tracks_raise() -> None:
    with pytest.raises(NotTranslatable):
        make_track(translatable=False).translate("tr")
