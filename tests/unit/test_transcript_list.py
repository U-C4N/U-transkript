import pytest

from transcript_list import TranscriptList
from fetched_transcript import FetchedTranscript
from exceptions import NoTranscriptFound


def _make_transcript_data(languages, generated=None, translatable=True):
    """Helper to build transcript_data dicts for TranscriptList."""
    if generated is None:
        generated = {lang: False for lang in languages}

    data = {}
    for lang_code, lang_name in languages.items():
        is_gen = generated.get(lang_code, False)
        data[lang_code] = [
            {
                "language_code": lang_code,
                "language": lang_name,
                "url": f"https://www.youtube.com/api/timedtext?v=test&lang={lang_code}",
                "is_generated": is_gen,
                "is_translatable": translatable,
                "translation_languages": [
                    {"language_code": "en", "language": "English"},
                    {"language_code": "tr", "language": "Turkish"},
                ]
                if translatable
                else [],
            }
        ]
    return data


class TestTranscriptListIteration:
    def test_iter_returns_all_transcripts(self):
        data = _make_transcript_data({"en": "English", "tr": "Turkish"})
        tl = TranscriptList("test_vid", data)
        transcripts = list(tl)
        assert len(transcripts) == 2

    def test_iter_returns_fetched_transcript_objects(self):
        data = _make_transcript_data({"en": "English"})
        tl = TranscriptList("test_vid", data)
        for t in tl:
            assert isinstance(t, FetchedTranscript)


class TestTranscriptListLen:
    def test_len_empty(self):
        tl = TranscriptList("test_vid", {})
        assert len(tl) == 0

    def test_len_multiple(self):
        data = _make_transcript_data({"en": "English", "tr": "Turkish", "de": "German"})
        tl = TranscriptList("test_vid", data)
        assert len(tl) == 3


class TestTranscriptListFindTranscript:
    def test_find_matching_language(self):
        data = _make_transcript_data({"en": "English", "tr": "Turkish"})
        tl = TranscriptList("test_vid", data)
        t = tl.find_transcript(["en"])
        assert t.language_code == "en"

    def test_find_second_preference(self):
        data = _make_transcript_data({"tr": "Turkish"})
        tl = TranscriptList("test_vid", data)
        t = tl.find_transcript(["en", "tr"])
        assert t.language_code == "tr"

    def test_find_no_match_raises(self):
        data = _make_transcript_data({"en": "English"}, translatable=False)
        tl = TranscriptList("test_vid", data)
        with pytest.raises(NoTranscriptFound):
            tl.find_transcript(["de", "fr"])


class TestTranscriptListFindGenerated:
    def test_find_generated_transcript(self):
        data = _make_transcript_data(
            {"en": "English", "tr": "Turkish"},
            generated={"en": True, "tr": False},
        )
        tl = TranscriptList("test_vid", data)
        t = tl.find_generated_transcript(["en"])
        assert t.language_code == "en"
        assert t.is_generated is True

    def test_find_generated_no_match_raises(self):
        data = _make_transcript_data(
            {"en": "English"},
            generated={"en": False},
            translatable=False,
        )
        tl = TranscriptList("test_vid", data)
        with pytest.raises(NoTranscriptFound):
            tl.find_generated_transcript(["en"])


class TestTranscriptListFindManuallyCreated:
    def test_find_manually_created(self):
        data = _make_transcript_data(
            {"en": "English", "tr": "Turkish"},
            generated={"en": True, "tr": False},
        )
        tl = TranscriptList("test_vid", data)
        t = tl.find_manually_created_transcript(["tr"])
        assert t.language_code == "tr"
        assert t.is_generated is False

    def test_find_manually_created_no_match_raises(self):
        data = _make_transcript_data(
            {"en": "English"},
            generated={"en": True},
            translatable=False,
        )
        tl = TranscriptList("test_vid", data)
        with pytest.raises(NoTranscriptFound):
            tl.find_manually_created_transcript(["en"])


class TestTranscriptListGetLanguages:
    def test_get_languages(self):
        data = _make_transcript_data({"en": "English", "tr": "Turkish"})
        tl = TranscriptList("test_vid", data)
        languages = tl.get_languages()
        assert set(languages) == {"en", "tr"}

    def test_get_languages_empty(self):
        tl = TranscriptList("test_vid", {})
        assert tl.get_languages() == []

    def test_get_generated_languages(self):
        data = _make_transcript_data(
            {"en": "English", "tr": "Turkish"},
            generated={"en": True, "tr": False},
        )
        tl = TranscriptList("test_vid", data)
        assert tl.get_generated_languages() == ["en"]

    def test_get_manually_created_languages(self):
        data = _make_transcript_data(
            {"en": "English", "tr": "Turkish"},
            generated={"en": True, "tr": False},
        )
        tl = TranscriptList("test_vid", data)
        assert tl.get_manually_created_languages() == ["tr"]


class TestTranscriptListRepr:
    def test_repr_contains_video_id(self):
        data = _make_transcript_data({"en": "English"})
        tl = TranscriptList("test_vid", data)
        r = repr(tl)
        assert "test_vid" in r

    def test_repr_contains_language(self):
        data = _make_transcript_data({"en": "English"})
        tl = TranscriptList("test_vid", data)
        r = repr(tl)
        assert "en" in r

    def test_repr_shows_generated_flag(self):
        data = _make_transcript_data(
            {"en": "English"}, generated={"en": True}
        )
        tl = TranscriptList("test_vid", data)
        r = repr(tl)
        assert "GENERATED" in r

    def test_repr_shows_translatable_flag(self):
        data = _make_transcript_data({"en": "English"}, translatable=True)
        tl = TranscriptList("test_vid", data)
        r = repr(tl)
        assert "TRANSLATABLE" in r
