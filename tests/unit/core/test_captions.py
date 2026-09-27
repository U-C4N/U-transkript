"""Tests for caption URLs and the json3/XML parsers."""

from __future__ import annotations

import json

import pytest

from tests.helpers.youtube import ASR_JSON3, LEGACY_XML, MANUAL_JSON3, SRV3_ASR_XML, VIDEO_ID
from utmax.core.captions import (
    caption_url,
    check_caption_url,
    parse_captions,
    parse_json3,
    parse_xml,
    set_query_param,
)
from utmax.errors import PoTokenRequired, YouTubeDataUnparsable
from utmax.models import Segment, Word

BASE = f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en&fmt=srv3"


def test_set_query_param_replaces_adds_and_removes() -> None:
    root = f"https://www.youtube.com/api/timedtext?v={VIDEO_ID}&lang=en"
    assert set_query_param(BASE, "fmt", "json3") == f"{root}&fmt=json3"
    assert set_query_param(BASE, "tlang", "tr") == f"{root}&fmt=srv3&tlang=tr"
    assert set_query_param(BASE, "fmt", None) == root
    assert set_query_param("https://x.youtube.com/a?empty=&k=1", "k", "2") == (
        "https://x.youtube.com/a?empty=&k=2"
    )


def test_caption_url_sets_the_format() -> None:
    assert caption_url(BASE).endswith("&lang=en&fmt=json3")
    assert "fmt=" not in caption_url(BASE, fmt=None)


@pytest.mark.parametrize(
    "url",
    [
        BASE,
        "https://youtube.com/api/timedtext?v=x",
        "https://m.youtube.com/api/timedtext?v=x&exp=abc,def",
    ],
)
def test_youtube_caption_urls_are_accepted(url: str) -> None:
    check_caption_url(url, video_id=VIDEO_ID)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/api/timedtext?v=x",
        "https://evil.example/api/timedtext",
        "https://youtube.com.evil.example/x",
        "https://notyoutube.com/x",
        "not a url",
    ],
)
def test_other_hosts_are_refused(url: str) -> None:
    with pytest.raises(YouTubeDataUnparsable):
        check_caption_url(url, video_id=VIDEO_ID)


@pytest.mark.parametrize("exp", ["xpe", "abc,xpe"])
def test_proof_of_origin_urls_are_refused(exp: str) -> None:
    with pytest.raises(PoTokenRequired):
        check_caption_url(f"{BASE}&exp={exp}", video_id=VIDEO_ID)


def test_manual_json3_keeps_line_breaks_and_has_no_words() -> None:
    assert parse_json3(MANUAL_JSON3, is_generated=False) == (
        Segment(1.36, 1.68, "[♪♪♪]"),
        Segment(18.64, 3.24, "♪ We're no strangers to love ♪"),
        Segment(22.64, 4.32, "♪ You know the rules\nand so do I ♪"),
    )


def test_auto_json3_skips_window_and_newline_events_and_keeps_words() -> None:
    music, words = parse_json3(ASR_JSON3, is_generated=True)
    assert (music.start, music.duration, music.text) == (0.32, 14.26, "[Music]")
    assert music.words == (Word("[Music]", 0.32),)
    assert (words.start, words.text) == (18.8, "We're no strangers to")
    assert [word.text for word in words.words] == ["We're", "no", "strangers", "to"]
    assert [word.start for word in words.words] == pytest.approx([18.8, 19.039, 19.359, 19.84])


def test_json3_formatting_tags_are_optional() -> None:
    styled = {
        "pens": [{}, {"bAttr": 1}, {"iAttr": 1, "uAttr": 1}],
        "events": [
            {
                "tStartMs": 0,
                "dDurationMs": 1000,
                "segs": [
                    {"utf8": "plain "},
                    {"utf8": "bold", "pPenId": 1},
                    {"utf8": " and "},
                    {"utf8": "fancy", "pPenId": 2},
                ],
            }
        ],
    }
    assert parse_json3(styled, is_generated=False)[0].text == "plain bold and fancy"
    assert parse_json3(styled, is_generated=False, preserve_formatting=True)[0].text == (
        "plain <b>bold</b> and <i><u>fancy</u></i>"
    )


def test_json3_entities_are_unescaped_and_odd_shapes_are_ignored() -> None:
    data = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 500, "segs": [{"utf8": "Tom &amp; Jerry"}]},
            "not an event",
            {"segs": "not a list"},
            {"tStartMs": 1000},
        ]
    }
    assert parse_json3(data, is_generated=False) == (Segment(0.0, 0.5, "Tom & Jerry"),)
    assert parse_json3({"events": "nope"}, is_generated=False) == ()


def test_legacy_xml_unescapes_double_escaped_entities() -> None:
    segments = parse_xml(LEGACY_XML, is_generated=False)
    assert [segment.text for segment in segments] == [
        "[♪♪♪]",
        "♪ We're no strangers to love ♪",
        "♪ You know the rules\nand so do I ♪",
    ]
    assert (segments[1].start, segments[1].duration, segments[1].words) == (18.64, 3.24, ())
    assert parse_xml(LEGACY_XML, is_generated=True)[0].words == (Word("[♪♪♪]", 1.36),)


def test_srv3_auto_captions_have_word_timings() -> None:
    music, words = parse_xml(SRV3_ASR_XML, is_generated=True)
    assert (music.text, music.words) == ("[Music]", (Word("[Music]", 0.32),))
    assert words.text == "We're no strangers to"
    assert [word.start for word in words.words] == pytest.approx([18.8, 19.039, 19.359, 19.84])


def test_xml_formatting_tags() -> None:
    xml = (
        '<transcript><text start="0" dur="1">'
        '&lt;i&gt;hi&lt;/i&gt; &lt;font color="red"&gt;x&lt;/font&gt;</text></transcript>'
    )
    assert parse_xml(xml, is_generated=False)[0].text == "hi x"
    assert parse_xml(xml, is_generated=False, preserve_formatting=True)[0].text == "<i>hi</i> x"


@pytest.mark.parametrize(
    "xml", ['<!DOCTYPE x [<!ENTITY a "b">]><transcript/>', "<transcript><text>", "<unknown/>"]
)
def test_unsafe_malformed_or_unknown_xml_is_unparsable(xml: str) -> None:
    with pytest.raises(YouTubeDataUnparsable):
        parse_xml(xml, is_generated=False, video_id=VIDEO_ID)


def test_parse_captions_dispatches_on_content() -> None:
    body = json.dumps(MANUAL_JSON3).encode()
    assert len(parse_captions(body, "application/json; charset=UTF-8", is_generated=False)) == 3
    assert len(parse_captions(body, "text/plain", is_generated=False)) == 3
    assert len(parse_captions(LEGACY_XML.encode(), "text/xml", is_generated=False)) == 3
    assert len(parse_captions(b"\xef\xbb\xbf" + LEGACY_XML.encode(), "", is_generated=False)) == 3


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"   ",
        b"hello",
        b"{oops",
        b"[1, 2]",
        b'{"events": [{"tStartMs": "soon", "segs": [{"utf8": "x"}]}]}',
        b'<transcript><text start="x">a</text></transcript>',
    ],
)
def test_parse_captions_turns_bad_bodies_into_typed_errors(body: bytes) -> None:
    with pytest.raises(YouTubeDataUnparsable):
        parse_captions(body, "", is_generated=False, video_id=VIDEO_ID)


def test_empty_caption_files_suggest_a_proof_of_origin_change() -> None:
    with pytest.raises(YouTubeDataUnparsable) as caught:
        parse_captions(b"", "application/json", is_generated=False)
    assert "proof-of-origin" in caught.value.suggestion


def test_json_captions_must_be_an_object() -> None:
    with pytest.raises(YouTubeDataUnparsable):
        parse_captions(b"[1, 2]", "application/json", is_generated=False)


def test_srv3_without_a_body_has_no_segments() -> None:
    assert parse_xml('<timedtext format="3"/>', is_generated=False) == ()
