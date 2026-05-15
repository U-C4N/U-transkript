import json
import pytest

from formatters import (
    JSONFormatter,
    TextFormatter,
    SRTFormatter,
    VTTFormatter,
    PrettyPrintFormatter,
    get_formatter,
)


class TestJSONFormatter:
    def test_format_empty_transcript(self):
        formatter = JSONFormatter()
        result = formatter.format_transcript([])
        assert json.loads(result) == []

    def test_format_single_entry(self, sample_transcript):
        formatter = JSONFormatter()
        result = formatter.format_transcript([sample_transcript[0]])
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["text"] == "Hello world"
        assert parsed[0]["start"] == 0.0
        assert parsed[0]["duration"] == 2.5

    def test_format_multiple_entries(self, sample_transcript):
        formatter = JSONFormatter()
        result = formatter.format_transcript(sample_transcript)
        parsed = json.loads(result)
        assert len(parsed) == 3
        assert parsed[2]["text"] == "YouTube transcript"

    def test_indent_option(self, sample_transcript):
        formatter = JSONFormatter()
        result = formatter.format_transcript(sample_transcript, indent=4)
        # 4-space indent should produce longer output than 2-space
        result_default = formatter.format_transcript(sample_transcript, indent=2)
        assert len(result) > len(result_default)

    def test_ensure_ascii_false(self):
        transcript = [{"text": "Merhaba dünya", "start": 0.0, "duration": 1.0}]
        formatter = JSONFormatter()
        result = formatter.format_transcript(transcript, ensure_ascii=False)
        assert "dünya" in result

    def test_ensure_ascii_true(self):
        transcript = [{"text": "Merhaba dünya", "start": 0.0, "duration": 1.0}]
        formatter = JSONFormatter()
        result = formatter.format_transcript(transcript, ensure_ascii=True)
        assert "dünya" not in result
        assert "\\u" in result

    def test_special_characters(self):
        transcript = [
            {"text": 'He said "hello" & <goodbye>', "start": 0.0, "duration": 1.0}
        ]
        formatter = JSONFormatter()
        result = formatter.format_transcript(transcript)
        parsed = json.loads(result)
        assert parsed[0]["text"] == 'He said "hello" & <goodbye>'


class TestTextFormatter:
    def test_format_empty_transcript(self):
        formatter = TextFormatter()
        result = formatter.format_transcript([])
        assert result == ""

    def test_format_single_entry(self, sample_transcript):
        formatter = TextFormatter()
        result = formatter.format_transcript([sample_transcript[0]])
        assert result == "Hello world"

    def test_format_multiple_entries(self, sample_transcript):
        formatter = TextFormatter()
        result = formatter.format_transcript(sample_transcript)
        assert result == "Hello world This is a test YouTube transcript"

    def test_custom_separator(self, sample_transcript):
        formatter = TextFormatter()
        result = formatter.format_transcript(sample_transcript, separator="\n")
        assert result == "Hello world\nThis is a test\nYouTube transcript"

    def test_special_characters(self):
        transcript = [
            {"text": "Line with <html> & \"quotes\"", "start": 0.0, "duration": 1.0}
        ]
        formatter = TextFormatter()
        result = formatter.format_transcript(transcript)
        assert result == "Line with <html> & \"quotes\""


class TestSRTFormatter:
    def test_format_empty_transcript(self):
        formatter = SRTFormatter()
        result = formatter.format_transcript([])
        assert result == ""

    def test_format_single_entry(self):
        transcript = [{"text": "Hello world", "start": 0.0, "duration": 2.5}]
        formatter = SRTFormatter()
        result = formatter.format_transcript(transcript)
        assert "1\n" in result
        assert "00:00:00,000 --> 00:00:02,500" in result
        assert "Hello world" in result

    def test_format_multiple_entries(self, sample_transcript):
        formatter = SRTFormatter()
        result = formatter.format_transcript(sample_transcript)
        assert "1\n" in result
        assert "2\n" in result
        assert "3\n" in result

    def test_timestamp_formatting(self):
        transcript = [{"text": "Test", "start": 3661.5, "duration": 1.0}]
        formatter = SRTFormatter()
        result = formatter.format_transcript(transcript)
        # 3661.5 seconds = 1 hour, 1 minute, 1.5 seconds
        assert "01:01:01,500" in result

    def test_timestamp_end_time(self):
        transcript = [{"text": "Test", "start": 10.0, "duration": 5.0}]
        formatter = SRTFormatter()
        result = formatter.format_transcript(transcript)
        assert "00:00:10,000 --> 00:00:15,000" in result

    def test_special_characters(self):
        transcript = [
            {"text": "Text with <b>bold</b> & entities", "start": 0.0, "duration": 1.0}
        ]
        formatter = SRTFormatter()
        result = formatter.format_transcript(transcript)
        assert "Text with <b>bold</b> & entities" in result


class TestVTTFormatter:
    def test_format_empty_transcript(self):
        formatter = VTTFormatter()
        result = formatter.format_transcript([])
        assert result.startswith("WEBVTT")

    def test_format_single_entry(self):
        transcript = [{"text": "Hello world", "start": 0.0, "duration": 2.5}]
        formatter = VTTFormatter()
        result = formatter.format_transcript(transcript)
        assert result.startswith("WEBVTT")
        assert "00:00:00.000 --> 00:00:02.500" in result
        assert "Hello world" in result

    def test_vtt_uses_dot_not_comma(self):
        transcript = [{"text": "Test", "start": 1.5, "duration": 1.0}]
        formatter = VTTFormatter()
        result = formatter.format_transcript(transcript)
        # VTT uses dot separator, not comma like SRT
        assert "." in result.split("-->")[0]
        assert "," not in result.split("-->")[0].replace("WEBVTT", "")

    def test_format_multiple_entries(self, sample_transcript):
        formatter = VTTFormatter()
        result = formatter.format_transcript(sample_transcript)
        assert result.startswith("WEBVTT")
        assert "Hello world" in result
        assert "This is a test" in result
        assert "YouTube transcript" in result

    def test_timestamp_formatting(self):
        transcript = [{"text": "Test", "start": 3661.5, "duration": 1.0}]
        formatter = VTTFormatter()
        result = formatter.format_transcript(transcript)
        assert "01:01:01.500" in result

    def test_special_characters(self):
        transcript = [
            {"text": "Merhaba dünya", "start": 0.0, "duration": 1.0}
        ]
        formatter = VTTFormatter()
        result = formatter.format_transcript(transcript)
        assert "Merhaba dünya" in result


class TestPrettyPrintFormatter:
    def test_format_empty_transcript(self):
        formatter = PrettyPrintFormatter()
        result = formatter.format_transcript([])
        assert result == ""

    def test_format_with_timestamps(self, sample_transcript):
        formatter = PrettyPrintFormatter()
        result = formatter.format_transcript(sample_transcript, show_timestamps=True)
        assert "[00:00]" in result
        assert "Hello world" in result

    def test_format_without_timestamps(self, sample_transcript):
        formatter = PrettyPrintFormatter()
        result = formatter.format_transcript(sample_transcript, show_timestamps=False)
        assert "[" not in result
        assert "Hello world" in result

    def test_timestamp_hours(self):
        transcript = [{"text": "Test", "start": 3661.0, "duration": 1.0}]
        formatter = PrettyPrintFormatter()
        result = formatter.format_transcript(transcript, show_timestamps=True)
        # 3661 seconds = 1:01:01
        assert "[01:01:01]" in result

    def test_timestamp_minutes(self):
        transcript = [{"text": "Test", "start": 125.0, "duration": 1.0}]
        formatter = PrettyPrintFormatter()
        result = formatter.format_transcript(transcript, show_timestamps=True)
        # 125 seconds = 02:05
        assert "[02:05]" in result

    def test_line_wrapping(self):
        long_text = "a " * 100  # Very long line
        transcript = [{"text": long_text.strip(), "start": 0.0, "duration": 1.0}]
        formatter = PrettyPrintFormatter()
        result = formatter.format_transcript(
            transcript, show_timestamps=True, max_chars_per_line=40
        )
        lines = result.split("\n")
        assert len(lines) > 1  # Should be wrapped

    def test_no_wrapping_for_short_lines(self, sample_transcript):
        formatter = PrettyPrintFormatter()
        result = formatter.format_transcript(
            sample_transcript, show_timestamps=True, max_chars_per_line=200
        )
        lines = result.split("\n")
        assert len(lines) == 3

    def test_format_long_transcript(self, sample_transcript_long):
        formatter = PrettyPrintFormatter()
        result = formatter.format_transcript(
            sample_transcript_long, show_timestamps=True
        )
        assert "Segment 0" in result
        assert "Segment 99" in result


class TestGetFormatter:
    def test_get_json_formatter(self):
        formatter = get_formatter("json")
        assert isinstance(formatter, JSONFormatter)

    def test_get_text_formatter(self):
        formatter = get_formatter("text")
        assert isinstance(formatter, TextFormatter)

    def test_get_srt_formatter(self):
        formatter = get_formatter("srt")
        assert isinstance(formatter, SRTFormatter)

    def test_get_vtt_formatter(self):
        formatter = get_formatter("vtt")
        assert isinstance(formatter, VTTFormatter)

    def test_get_pretty_formatter(self):
        formatter = get_formatter("pretty")
        assert isinstance(formatter, PrettyPrintFormatter)

    def test_case_insensitive(self):
        formatter = get_formatter("JSON")
        assert isinstance(formatter, JSONFormatter)

    def test_invalid_formatter_raises_valueerror(self):
        with pytest.raises(ValueError, match="Unknown formatter"):
            get_formatter("invalid")

    def test_invalid_formatter_lists_available(self):
        with pytest.raises(ValueError, match="Available"):
            get_formatter("nonexistent")
