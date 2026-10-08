"""youtube-transcript-api 1.2.4's formatter tests, run against utmax.compat.formatters, plus
byte-exact output and the dictionaries of version 0.6."""

from __future__ import annotations

import json
import pprint

import pytest

from utmax.compat.formatters import (
    FetchedTranscript,
    FetchedTranscriptSnippet,
    Formatter,
    FormatterLoader,
    JSONFormatter,
    PrettyPrintFormatter,
    SRTFormatter,
    TextFormatter,
    WebVTTFormatter,
)

SRT = (
    "1\n00:00:00,000 --> 00:00:01,500\nTest line 1\n\n"
    "2\n00:00:01,500 --> 00:00:02,500\nline between\n\n"
    "3\n00:00:02,500 --> 00:00:05,750\ntesting the end line\n"
)
WEBVTT = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:01.500\nTest line 1\n\n"
    "00:00:01.500 --> 00:00:02.500\nline between\n\n"
    "00:00:02.500 --> 00:00:05.750\ntesting the end line\n"
)


@pytest.fixture
def transcript() -> FetchedTranscript:
    return FetchedTranscript(
        snippets=[
            FetchedTranscriptSnippet(text="Test line 1", start=0.0, duration=1.50),
            FetchedTranscriptSnippet(text="line between", start=1.5, duration=2.0),
            FetchedTranscriptSnippet(text="testing the end line", start=2.5, duration=3.25),
        ],
        language="English",
        language_code="en",
        is_generated=True,
        video_id="12345",
    )


def test_base_formatter_format_call(transcript: FetchedTranscript) -> None:
    with pytest.raises(NotImplementedError):
        Formatter().format_transcript(transcript)
    with pytest.raises(NotImplementedError):
        Formatter().format_transcripts([transcript])


def test_srt_formatter_starting(transcript: FetchedTranscript) -> None:
    lines = SRTFormatter().format_transcript(transcript).split("\n")

    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:01,500"


def test_srt_formatter_middle(transcript: FetchedTranscript) -> None:
    lines = SRTFormatter().format_transcript(transcript).split("\n")

    assert lines[4] == "2"
    assert lines[5] == "00:00:01,500 --> 00:00:02,500"
    assert lines[6] == transcript.to_raw_data()[1]["text"]


def test_srt_formatter_ending(transcript: FetchedTranscript) -> None:
    lines = SRTFormatter().format_transcript(transcript).split("\n")

    assert lines[-2] == transcript.to_raw_data()[-1]["text"]
    assert lines[-1] == ""


def test_srt_formatter_many(transcript: FetchedTranscript) -> None:
    formatter = SRTFormatter()
    content = formatter.format_transcripts([transcript, transcript])
    single = formatter.format_transcript(transcript)

    assert content == single + "\n\n\n" + single


def test_webvtt_formatter_starting(transcript: FetchedTranscript) -> None:
    lines = WebVTTFormatter().format_transcript(transcript).split("\n")

    assert lines[0] == "WEBVTT"
    assert lines[1] == ""


def test_webvtt_formatter_ending(transcript: FetchedTranscript) -> None:
    lines = WebVTTFormatter().format_transcript(transcript).split("\n")

    assert lines[-2] == transcript.to_raw_data()[-1]["text"]
    assert lines[-1] == ""


def test_webvtt_formatter_many(transcript: FetchedTranscript) -> None:
    formatter = WebVTTFormatter()
    content = formatter.format_transcripts([transcript, transcript])
    single = formatter.format_transcript(transcript)

    assert content == single + "\n\n\n" + single


def test_pretty_print_formatter(transcript: FetchedTranscript) -> None:
    content = PrettyPrintFormatter().format_transcript(transcript)

    assert content == pprint.pformat(transcript.to_raw_data())


def test_pretty_print_formatter_many(transcript: FetchedTranscript) -> None:
    content = PrettyPrintFormatter().format_transcripts([transcript, transcript])

    assert content == pprint.pformat([transcript.to_raw_data()] * 2)


def test_json_formatter(transcript: FetchedTranscript) -> None:
    content = JSONFormatter().format_transcript(transcript)

    assert json.loads(content) == transcript.to_raw_data()


def test_json_formatter_many(transcript: FetchedTranscript) -> None:
    content = JSONFormatter().format_transcripts([transcript, transcript])

    assert json.loads(content) == [transcript.to_raw_data()] * 2


def test_text_formatter(transcript: FetchedTranscript) -> None:
    lines = TextFormatter().format_transcript(transcript).split("\n")

    assert lines[0] == transcript.to_raw_data()[0]["text"]
    assert lines[-1] == transcript.to_raw_data()[-1]["text"]


def test_text_formatter_many(transcript: FetchedTranscript) -> None:
    formatter = TextFormatter()
    content = formatter.format_transcripts([transcript, transcript])
    single = formatter.format_transcript(transcript)

    assert content == single + "\n\n\n" + single


def test_formatter_loader() -> None:
    assert isinstance(FormatterLoader().load("json"), JSONFormatter)


def test_formatter_loader__default_formatter() -> None:
    assert isinstance(FormatterLoader().load(), PrettyPrintFormatter)


def test_formatter_loader__unknown_format() -> None:
    with pytest.raises(FormatterLoader.UnknownFormatterType) as caught:
        FormatterLoader().load("png")

    assert str(caught.value) == (
        "The format 'png' is not supported. "
        "Choose one of the following formats: json, pretty, text, webvtt, srt"
    )


def test_the_output_is_byte_exact(transcript: FetchedTranscript) -> None:
    assert SRTFormatter().format_transcript(transcript) == SRT
    assert WebVTTFormatter().format_transcript(transcript) == WEBVTT
    assert JSONFormatter().format_transcript(transcript, indent=None) == (
        '[{"text": "Test line 1", "start": 0.0, "duration": 1.5}, '
        '{"text": "line between", "start": 1.5, "duration": 2.0}, '
        '{"text": "testing the end line", "start": 2.5, "duration": 3.25}]'
    )
    assert TextFormatter().format_transcript(transcript) == (
        "Test line 1\nline between\ntesting the end line"
    )


def test_a_cue_before_a_pause_ends_at_its_own_end() -> None:
    # A cue ends where the next one starts only when the two overlap. The shared transcript has
    # no pause, so this one has: the first cue must not stretch across it.
    paused = FetchedTranscript(
        snippets=[
            FetchedTranscriptSnippet(text="before the pause", start=0.0, duration=1.0),
            FetchedTranscriptSnippet(text="after the pause", start=5.0, duration=1.0),
        ],
        language="English",
        language_code="en",
        is_generated=False,
        video_id="12345",
    )

    assert SRTFormatter().format_transcript(paused) == (
        "1\n00:00:00,000 --> 00:00:01,000\nbefore the pause\n\n"
        "2\n00:00:05,000 --> 00:00:06,000\nafter the pause\n"
    )
    assert WebVTTFormatter().format_transcript(paused) == (
        "WEBVTT\n\n"
        "00:00:00.000 --> 00:00:01.000\nbefore the pause\n\n"
        "00:00:05.000 --> 00:00:06.000\nafter the pause\n"
    )


def test_options_reach_json_dumps_and_pformat(transcript: FetchedTranscript) -> None:
    raw = transcript.to_raw_data()

    # The options must change the output, or this test would pin nothing.
    assert json.dumps(raw, indent=2) != json.dumps(raw)
    assert pprint.pformat(raw, width=20) != pprint.pformat(raw)

    assert JSONFormatter().format_transcript(transcript, indent=2) == json.dumps(raw, indent=2)
    assert JSONFormatter().format_transcripts([transcript], indent=2) == json.dumps([raw], indent=2)
    assert PrettyPrintFormatter().format_transcript(transcript, width=20) == pprint.pformat(
        raw, width=20
    )
    assert PrettyPrintFormatter().format_transcripts([transcript], width=20) == pprint.pformat(
        [raw], width=20
    )


@pytest.mark.parametrize(
    ("seconds", "srt"),
    [
        (6.93, "00:00:06,930"),
        (59.9999, "00:00:59,999"),
        (1.9999999, "00:00:01,1000"),
        (3725.5, "01:02:05,500"),
        (0.0004, "00:00:00,000"),
    ],
)
def test_timestamps_keep_youtube_transcript_api_rounding(seconds: float, srt: str) -> None:
    assert SRTFormatter()._seconds_to_timestamp(seconds) == srt


def test_dictionaries_of_version_0_6_format_the_same(transcript: FetchedTranscript) -> None:
    raw = transcript.to_raw_data()

    for formatter in (
        SRTFormatter(),
        WebVTTFormatter(),
        JSONFormatter(),
        TextFormatter(),
        PrettyPrintFormatter(),
    ):
        assert formatter.format_transcript(raw) == formatter.format_transcript(transcript)
        assert formatter.format_transcripts([raw, raw]) == formatter.format_transcripts(
            [transcript, transcript]
        )
