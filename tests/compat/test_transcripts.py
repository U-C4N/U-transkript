"""Transcripts and transcript lists of utmax.compat, built from a faked YouTube."""

from __future__ import annotations

from xml.etree import ElementTree

import pytest

from tests.helpers.compat import (
    RAW_DATA,
    TRANSCRIPT_XML,
    VIDEO,
    FakeSession,
    compat_youtube,
    xml_response,
)
from tests.helpers.fake_transport import FakeTransport, text_response
from tests.helpers.youtube import caption_track, player_payload
from utmax import errors
from utmax.compat._bridge import Connection
from utmax.compat._errors import (
    NoTranscriptFound,
    NotTranslatable,
    PoTokenRequired,
    TranslationLanguageNotAvailable,
    YouTubeDataUnparsable,
)
from utmax.compat._transcripts import (
    FetchedTranscript,
    FetchedTranscriptSnippet,
    Transcript,
    TranscriptList,
    TranscriptListFetcher,
    _TranscriptParser,
    _TranslationLanguage,
)
from utmax.transport import HttpResponse

LIST_TEXT = (
    "For this video (GJLlxj_dtq8) transcripts are available in the following languages:\n\n"
    "(MANUALLY CREATED)\n"
    ' - de ("German")[TRANSLATABLE]\n'
    ' - en ("English")\n\n'
    "(GENERATED)\n"
    ' - en ("English (auto-generated)")[TRANSLATABLE]\n\n'
    "(TRANSLATION LANGUAGES)\n"
    ' - ar ("Arabic")\n'
    ' - de ("German")\n'
    ' - en ("English")'
)


def transcript_list(transport: FakeTransport | None = None) -> TranscriptList:
    return TranscriptListFetcher(FakeSession(transport or compat_youtube()), None).fetch(VIDEO)


def small_list() -> TranscriptList:
    payload = player_payload(
        video_id=VIDEO,
        tracks=(("de", "German", False), ("en", "English", False)),
        translation_languages=(("ar", "Arabic"), ("de", "German"), ("en", "English")),
    )
    renderer = payload["captions"]["playerCaptionsTracklistRenderer"]
    renderer["captionTracks"][1]["isTranslatable"] = False
    renderer["captionTracks"].append(caption_track("en", "English (auto-generated)", True))
    return TranscriptList.build(FakeSession(FakeTransport()), VIDEO, renderer)


def test_the_parser_reads_legacy_xml_like_youtube_transcript_api() -> None:
    parser = _TranscriptParser()
    formatted = _TranscriptParser(preserve_formatting=True).parse(TRANSCRIPT_XML)

    assert [snippet.__dict__ for snippet in parser.parse(TRANSCRIPT_XML)] == RAW_DATA
    assert formatted[1].text == 'today we <i>really</i> build "it"'


def test_the_parser_keeps_whitespace_and_defaults_the_duration() -> None:
    xml = '<transcript><text start="2">  two\nlines  </text><text start="3"> </text></transcript>'

    assert _TranscriptParser().parse(xml) == [
        FetchedTranscriptSnippet(text="  two\nlines  ", start=2.0, duration=0.0),
        FetchedTranscriptSnippet(text=" ", start=3.0, duration=0.0),
    ]


def test_the_parser_drops_tags_except_formatting_ones() -> None:
    xml = (
        "<transcript><text start='0' dur='1'>"
        "&lt;b&gt;bold&lt;/b&gt; &lt;font color=red&gt;red&lt;/font&gt;"
        "</text></transcript>"
    )

    assert _TranscriptParser().parse(xml)[0].text == "bold red"
    assert _TranscriptParser(preserve_formatting=True).parse(xml)[0].text == "<b>bold</b> red"


def test_the_parser_refuses_entity_declarations() -> None:
    with pytest.raises(ValueError, match="DOCTYPE"):
        _TranscriptParser().parse('<!DOCTYPE x [<!ENTITY a "b">]><transcript/>')


def test_lists_hold_manual_then_generated_transcripts() -> None:
    transcripts = transcript_list()

    assert transcripts.video_id == VIDEO
    assert [(t.language_code, t.is_generated) for t in transcripts] == [
        ("zh", False),
        ("de", False),
        ("en", False),
        ("hi", False),
        ("ja", False),
        ("ko", False),
        ("es", False),
        ("cs", False),
        ("en", True),
    ]
    english = transcripts.find_transcript(["en"])
    assert (english.language, english._url) == (
        "English",
        f"https://www.youtube.com/api/timedtext?v={VIDEO}&lang=en",
    )
    assert [language.language_code for language in english.translation_languages] == [
        "ar",
        "de",
        "en",
    ]


def test_a_later_track_in_the_same_language_replaces_an_earlier_one() -> None:
    tracks = (("en", "English", False), ("de", "German", False), ("en", "English (UK)", False))

    transcripts = transcript_list(compat_youtube(tracks=tracks))

    assert [(t.language_code, t.language) for t in transcripts] == [
        ("en", "English (UK)"),
        ("de", "German"),
    ]


def test_the_list_describes_itself_like_youtube_transcript_api() -> None:
    transcripts = small_list()

    assert str(transcripts) == LIST_TEXT
    assert str(TranscriptList(VIDEO, {}, {}, [])).count("\nNone") == 3


def test_finding_transcripts_matches_exact_codes_manual_first() -> None:
    transcripts = transcript_list()

    assert transcripts.find_transcript(["de", "en"]).language_code == "de"
    assert transcripts.find_transcript(["xx", "en"]).is_generated is False
    assert transcripts.find_manually_created_transcript(["cs"]).is_generated is False
    assert transcripts.find_generated_transcript(["en"]).is_generated is True
    with pytest.raises(NoTranscriptFound):
        transcripts.find_generated_transcript(["cs"])


def test_no_transcript_found_lists_what_exists() -> None:
    transcripts = small_list()

    with pytest.raises(NoTranscriptFound) as caught:
        transcripts.find_transcript(["cz"])

    message = str(caught.value)
    assert "No transcripts were found for any of the requested language codes: ['cz']" in message
    assert LIST_TEXT in message


def test_translation_builds_a_tlang_transcript() -> None:
    english = transcript_list().find_transcript(["en"])

    arabic = english.translate("ar")

    assert (arabic.language_code, arabic.language, arabic.is_generated) == ("ar", "Arabic", True)
    assert arabic._url == f"{english._url}&tlang=ar"
    assert arabic.translation_languages == []
    assert str(arabic) == 'ar ("Arabic")'
    assert str(english) == 'en ("English")[TRANSLATABLE]'


def test_translation_errors() -> None:
    english = transcript_list().find_transcript(["en"])

    with pytest.raises(TranslationLanguageNotAvailable):
        english.translate("xyz")
    english.translation_languages = []
    with pytest.raises(NotTranslatable):
        english.translate("af")


def test_fetching_downloads_and_parses_legacy_xml() -> None:
    transport = compat_youtube()

    fetched = transcript_list(transport).find_transcript(["de"]).fetch()

    assert fetched == FetchedTranscript(
        snippets=[FetchedTranscriptSnippet(**line) for line in RAW_DATA],
        video_id=VIDEO,
        language="German",
        language_code="de",
        is_generated=False,
    )
    assert transport.urls("GET") == [f"https://www.youtube.com/api/timedtext?v={VIDEO}&lang=de"]


def test_fetched_transcripts_behave_like_lists() -> None:
    fetched = transcript_list().find_transcript(["en"]).fetch(preserve_formatting=True)

    assert len(fetched) == 3
    assert [snippet.start for snippet in fetched] == [0.0, 1.5, 5.7]
    assert fetched[1].text == 'today we <i>really</i> build "it"'
    assert fetched[1:] == fetched.snippets[1:]
    assert fetched.to_raw_data()[0] == RAW_DATA[0]


def test_po_token_urls_fail_without_a_request() -> None:
    transport = FakeTransport()
    transcript = Transcript(
        Connection(transport),
        VIDEO,
        f"https://www.youtube.com/api/timedtext?v={VIDEO}&exp=xpe&lang=en",
        "English",
        "en",
        False,
        [],
    )

    with pytest.raises(PoTokenRequired):
        transcript.fetch()
    assert transport.requests == []


@pytest.mark.parametrize(
    "answer",
    [
        xml_response("<transcript><text>no start</text></transcript>"),
        xml_response("<transcript>"),
        text_response("<!doctype html><html>Before you continue</html>"),
    ],
)
def test_unreadable_captions_are_unparsable(answer: HttpResponse) -> None:
    transport = FakeTransport()
    transport.add("GET", "/api/timedtext", answer)
    transcript = Transcript(
        Connection(transport),
        VIDEO,
        f"https://www.youtube.com/api/timedtext?v={VIDEO}&lang=en",
        "English",
        "en",
        False,
        [],
    )

    with pytest.raises(YouTubeDataUnparsable) as caught:
        transcript.fetch()
    assert isinstance(caught.value.__cause__, ElementTree.ParseError | KeyError | ValueError)


def test_hand_built_transcripts_fetch_through_their_http_client() -> None:
    session = FakeSession(compat_youtube())
    language = _TranslationLanguage(language="Arabic", language_code="ar")
    transcript = Transcript(
        session,
        VIDEO,
        f"https://www.youtube.com/api/timedtext?v={VIDEO}&lang=en",
        "English",
        "en",
        False,
        [language],
    )

    assert transcript.fetch().to_raw_data() == RAW_DATA
    assert transcript.is_translatable is True
    assert transcript.translate("ar").fetch().language_code == "ar"


def test_snippets_read_like_the_dictionaries_of_version_0_6() -> None:
    pieces = transcript_list().find_transcript(["en"]).fetch()
    first = pieces[0]

    assert " ".join(piece["text"] for piece in pieces) == " ".join(
        line["text"] for line in RAW_DATA
    )
    assert [dict(piece) for piece in pieces] == RAW_DATA
    assert (first.get("start"), first.get("words"), first.get("words", [])) == (0.0, None, [])
    assert list(first) == list(first.keys()) == ["text", "start", "duration"]
    assert first.values() == list(RAW_DATA[0].values())
    assert first.items() == list(RAW_DATA[0].items())
    assert ("duration" in first, "words" in first, len(first)) == (True, False, 3)
    with pytest.raises(KeyError, match="words"):
        _ = first["words"]
    assert pieces.to_raw_data() == RAW_DATA


@pytest.mark.parametrize(
    ("url", "error"),
    [
        (f"https://evil.example/api/timedtext?v={VIDEO}&lang=en", YouTubeDataUnparsable),
        (f"http://www.youtube.com/api/timedtext?v={VIDEO}&lang=en", YouTubeDataUnparsable),
        (f"https://www.youtube.com/api/timedtext?v={VIDEO}&exp=abc,xpe&lang=en", PoTokenRequired),
    ],
)
def test_unsafe_caption_urls_fail_without_a_request(url: str, error: type[Exception]) -> None:
    transport = FakeTransport()
    transcript = Transcript(Connection(transport), VIDEO, url, "English", "en", False, [])

    with pytest.raises(error) as caught:
        transcript.fetch()

    assert isinstance(caught.value.__cause__, errors.YouTubeError)
    assert type(caught.value.__cause__).__name__ == error.__name__
    assert transport.requests == []
