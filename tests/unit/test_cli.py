import os
from unittest.mock import MagicMock, patch

import pytest

from cli.main import main
from cli.url_parser import (
    build_youtube_channel_url,
    extract_video_id,
    is_channel_target,
)


class TestExtractVideoId:
    def test_plain_video_id(self):
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_standard_url(self):
        assert (
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )

    def test_short_url(self):
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert (
            extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ")
            == "dQw4w9WgXcQ"
        )

    def test_url_with_extra_params(self):
        assert (
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120")
            == "dQw4w9WgXcQ"
        )

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Could not extract video ID"):
            extract_video_id("not-a-valid-url-or-id")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            extract_video_id("")

    def test_id_with_hyphens_underscores(self):
        assert extract_video_id("a_b-c_d-e_f") == "a_b-c_d-e_f"


class TestBuildYoutubeChannelUrl:
    def test_with_at_sign(self):
        url = build_youtube_channel_url("@MrBeast")
        assert "MrBeast" in url

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


class TestIsChannelTarget:
    @pytest.mark.parametrize(
        "target",
        [
            "@MrBeast",
            "UCX6OQ3DkcsbYNE6H8uQQuVA",
            "https://www.youtube.com/@MrBeast",
            "https://www.youtube.com/c/MrBeast",
            "https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA",
            "https://www.youtube.com/user/PewDiePie",
        ],
    )
    def test_channel_targets(self, target):
        assert is_channel_target(target)

    @pytest.mark.parametrize(
        "target",
        [
            "dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "",
        ],
    )
    def test_non_channel_targets(self, target):
        assert not is_channel_target(target)


class TestMainArgumentParsing:
    @patch("cli.single_video.YouTubeTranscriptApi")
    @patch("cli.single_video.get_formatter")
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

    @patch("cli.single_video.YouTubeTranscriptApi")
    @patch("cli.single_video.get_formatter")
    def test_format_json(self, mock_formatter, mock_api):
        mock_api.get_transcript.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 1.0}
        ]
        mock_fmt = MagicMock()
        mock_fmt.format_transcript.return_value = '{"text": "Hello"}'
        mock_formatter.return_value = mock_fmt

        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "-f", "json"]):
            main()

        mock_formatter.assert_called_with("json")

    @patch("cli.single_video.YouTubeTranscriptApi")
    @patch("cli.single_video.get_formatter")
    def test_output_to_file(self, mock_formatter, mock_api, tmp_path):
        mock_api.get_transcript.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 1.0}
        ]
        mock_fmt = MagicMock()
        mock_fmt.format_transcript.return_value = "Hello"
        mock_formatter.return_value = mock_fmt

        output_file = str(tmp_path / "output.txt")
        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "-o", output_file]):
            main()

        assert os.path.exists(output_file)
        with open(output_file, "r") as f:
            assert f.read() == "Hello"

    def test_invalid_video_id_exits(self):
        with patch("sys.argv", ["cli.py", "not_valid!!!"]):
            with pytest.raises(SystemExit):
                main()

    @patch("cli.single_video.YouTubeTranscriptApi")
    @patch("cli.single_video.get_formatter")
    def test_languages_flag(self, mock_formatter, mock_api):
        mock_api.get_transcript.return_value = [
            {"text": "Hola", "start": 0.0, "duration": 1.0}
        ]
        mock_fmt = MagicMock()
        mock_fmt.format_transcript.return_value = "Hola"
        mock_formatter.return_value = mock_fmt

        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "-l", "es", "en"]):
            main()

        kwargs = mock_api.get_transcript.call_args.kwargs
        assert kwargs["languages"] == ["es", "en"]

    @patch("cli.channel_downloader.get_channel_video_ids")
    @patch("cli.channel_downloader.YouTubeTranscriptApi")
    @patch("cli.channel_downloader.get_formatter")
    def test_channel_target_routes_to_bulk(
        self, mock_formatter, mock_api, mock_get_ids, tmp_path
    ):
        mock_get_ids.return_value = ["vid1", "vid2"]
        mock_api.get_transcript.return_value = [
            {"text": "Hi", "start": 0.0, "duration": 1.0}
        ]
        mock_fmt = MagicMock()
        mock_fmt.format_transcript.return_value = "Hi"
        mock_formatter.return_value = mock_fmt

        out_dir = str(tmp_path / "channel-out")
        with patch("sys.argv", ["cli.py", "@MrBeast", "-o", out_dir]):
            main()

        mock_get_ids.assert_called_once()
        assert os.path.isdir(out_dir)
