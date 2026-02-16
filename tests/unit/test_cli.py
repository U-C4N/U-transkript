import pytest
import sys
import os
from unittest.mock import patch, MagicMock

# cli.py is at the project root, add it to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from cli import extract_video_id, build_youtube_channel_url, main


class TestExtractVideoId:
    def test_plain_video_id(self):
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_standard_url(self):
        assert (
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )

    def test_short_url(self):
        assert (
            extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
        )

    def test_embed_url(self):
        assert (
            extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )

    def test_url_with_extra_params(self):
        assert (
            extract_video_id(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120"
            )
            == "dQw4w9WgXcQ"
        )

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Could not extract video ID"):
            extract_video_id("not-a-valid-url-or-id")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            extract_video_id("")

    def test_id_with_hyphens_underscores(self):
        # YouTube video IDs are exactly 11 characters
        assert extract_video_id("a_b-c_d-e_f") == "a_b-c_d-e_f"


class TestBuildYoutubeChannelUrl:
    def test_with_at_sign(self):
        url = build_youtube_channel_url("@MrBeast")
        assert "MrBeast" in url
        assert "@" in url or "MrBeast" in url

    def test_without_at_sign(self):
        url = build_youtube_channel_url("MrBeast")
        assert "MrBeast" in url

    def test_full_url_passthrough(self):
        full_url = "https://www.youtube.com/@MrBeast"
        assert build_youtube_channel_url(full_url) == full_url

    def test_channel_id(self):
        channel_id = "UCX6OQ3DkcsbYNE6H8uQQuVA"
        url = build_youtube_channel_url(channel_id)
        assert channel_id in url
        assert "channel" in url


class TestMainArgumentParsing:
    @patch("cli.YouTubeTranscriptApi")
    @patch("cli.get_formatter")
    def test_basic_video_arg(self, mock_formatter, mock_api):
        mock_api.get_transcript.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 1.0}
        ]
        mock_fmt = MagicMock()
        mock_fmt.format_transcript.return_value = "Hello"
        mock_formatter.return_value = mock_fmt

        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ"]):
            main()

        mock_api.get_transcript.assert_called_once()

    def test_no_args_exits(self):
        with patch("sys.argv", ["cli.py"]):
            with pytest.raises(SystemExit):
                main()

    @patch("cli.YouTubeTranscriptApi")
    @patch("cli.get_formatter")
    def test_format_json(self, mock_formatter, mock_api):
        mock_api.get_transcript.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 1.0}
        ]
        mock_fmt = MagicMock()
        mock_fmt.format_transcript.return_value = '{"text": "Hello"}'
        mock_formatter.return_value = mock_fmt

        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "--format", "json"]):
            main()

        mock_formatter.assert_called_with("json")

    @patch("cli.YouTubeTranscriptApi")
    @patch("cli.get_formatter")
    def test_output_to_file(self, mock_formatter, mock_api, tmp_path):
        mock_api.get_transcript.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 1.0}
        ]
        mock_fmt = MagicMock()
        mock_fmt.format_transcript.return_value = "Hello"
        mock_formatter.return_value = mock_fmt

        output_file = str(tmp_path / "output.txt")
        with patch(
            "sys.argv", ["cli.py", "dQw4w9WgXcQ", "--output", output_file]
        ):
            main()

        assert os.path.exists(output_file)
        with open(output_file, "r") as f:
            assert f.read() == "Hello"

    def test_both_video_and_username_exits(self):
        with patch(
            "sys.argv", ["cli.py", "dQw4w9WgXcQ", "--username", "@MrBeast"]
        ):
            with pytest.raises(SystemExit):
                main()

    @patch("cli.YouTubeTranscriptApi")
    def test_list_transcripts_flag(self, mock_api):
        mock_tl = MagicMock()
        mock_transcript = MagicMock()
        mock_transcript.language_code = "en"
        mock_transcript.language = "English"
        mock_transcript.is_generated = True
        mock_transcript.is_translatable = True
        mock_transcript.translation_languages = []
        mock_tl.__iter__ = MagicMock(return_value=iter([mock_transcript]))
        mock_api.list_transcripts.return_value = mock_tl

        with patch(
            "sys.argv", ["cli.py", "dQw4w9WgXcQ", "--list-transcripts"]
        ):
            main()

        mock_api.list_transcripts.assert_called_once()

    def test_invalid_video_id_exits(self):
        with patch("sys.argv", ["cli.py", "not_valid!!!"]):
            with pytest.raises(SystemExit):
                main()

    @patch("cli.YouTubeTranscriptApi")
    @patch("cli.get_formatter")
    def test_languages_flag(self, mock_formatter, mock_api):
        mock_api.get_transcript.return_value = [
            {"text": "Hola", "start": 0.0, "duration": 1.0}
        ]
        mock_fmt = MagicMock()
        mock_fmt.format_transcript.return_value = "Hola"
        mock_formatter.return_value = mock_fmt

        with patch(
            "sys.argv",
            ["cli.py", "dQw4w9WgXcQ", "--languages", "es", "en"],
        ):
            main()

        call_kwargs = mock_api.get_transcript.call_args
        assert call_kwargs[1]["languages"] == ["es", "en"] or call_kwargs.kwargs.get("languages") == ["es", "en"]
