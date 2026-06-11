import os
from unittest.mock import MagicMock, patch

import pytest

from cli.main import main
from cli.url_parser import (
    build_youtube_channel_url,
    extract_video_id,
    is_channel_target,
)
from exceptions import TranscriptRetrievalError


class _DummyCache:
    """In-memory stand-in for TranscriptCache so tests never touch the real disk cache."""

    def __init__(self, *args, **kwargs):
        pass

    def get(self, video_id, language="default"):
        return None

    def set(self, video_id, transcript, language="default"):
        pass


@pytest.fixture(autouse=True)
def _no_disk_cache(monkeypatch):
    monkeypatch.setattr("cli.helpers.TranscriptCache", _DummyCache)


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

        mock_get_ids.assert_called_once_with("@MrBeast", 10)
        assert os.path.isdir(out_dir)

    @patch("cli.channel_downloader.get_channel_video_ids")
    @patch("cli.channel_downloader.YouTubeTranscriptApi")
    def test_channel_all_failed_exits_api_error(self, mock_api, mock_get_ids, tmp_path):
        mock_get_ids.return_value = ["vid1", "vid2"]
        mock_api.get_transcript.side_effect = TranscriptRetrievalError("vid1", "boom")

        out_dir = str(tmp_path / "channel-out")
        with patch("sys.argv", ["cli.py", "@MrBeast", "-o", out_dir]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 3

    @patch("cli.channel_downloader.get_channel_video_ids")
    @patch("cli.channel_downloader.YouTubeTranscriptApi")
    @patch("cli.channel_downloader.get_formatter")
    def test_channel_count_flag_and_id_filenames(
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
        with patch("sys.argv", ["cli.py", "@MrBeast", "-o", out_dir, "-n", "25"]):
            main()

        mock_get_ids.assert_called_once_with("@MrBeast", 25)
        assert os.path.exists(os.path.join(out_dir, "1_vid1.txt"))
        assert os.path.exists(os.path.join(out_dir, "2_vid2.txt"))

    def test_count_rejects_non_positive(self):
        with patch("sys.argv", ["cli.py", "@MrBeast", "-n", "0"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 2  # argparse usage error


def _fake_transcript_list(transcripts):
    transcript_list = MagicMock()
    transcript_list.all_transcripts.return_value = transcripts
    return transcript_list


class TestListTranscripts:
    @patch("cli.listing.YouTubeTranscriptApi")
    def test_lists_languages(self, mock_api, capsys):
        transcript = MagicMock()
        transcript.language_code = "en"
        transcript.language = "English"
        transcript.is_generated = True
        transcript.is_translatable = True
        mock_api.list_transcripts.return_value = _fake_transcript_list([transcript])

        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "--list-transcripts"]):
            main()

        out = capsys.readouterr().out
        assert "Available transcripts for dQw4w9WgXcQ:" in out
        assert "  en       English (auto, translatable)" in out

    @patch("cli.listing.YouTubeTranscriptApi")
    def test_json_format(self, mock_api, capsys):
        transcript = MagicMock()
        transcript.language_code = "tr"
        transcript.language = "Turkish"
        transcript.is_generated = False
        transcript.is_translatable = False
        mock_api.list_transcripts.return_value = _fake_transcript_list([transcript])

        with patch(
            "sys.argv", ["cli.py", "dQw4w9WgXcQ", "--list-transcripts", "-f", "json"]
        ):
            main()

        out = capsys.readouterr().out
        assert '"language_code": "tr"' in out
        assert '"is_generated": false' in out

    @patch("cli.listing.YouTubeTranscriptApi")
    def test_retrieval_error_exits_api_error(self, mock_api):
        mock_api.list_transcripts.side_effect = TranscriptRetrievalError("vid", "boom")

        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "--list-transcripts"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 3

    def test_channel_target_exits_user_error(self):
        with patch("sys.argv", ["cli.py", "@MrBeast", "--list-transcripts"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1


class TestCacheWiring:
    class _SeededCache:
        store: dict = {}
        constructions = 0

        def __init__(self, *args, **kwargs):
            type(self).constructions += 1

        def get(self, video_id, language="default"):
            return self.store.get((video_id, language))

        def set(self, video_id, transcript, language="default"):
            self.store[(video_id, language)] = transcript

    @pytest.fixture(autouse=True)
    def _seeded_cache(self, monkeypatch, _no_disk_cache):
        # depends on _no_disk_cache so this patch deterministically wins
        monkeypatch.setattr("cli.helpers.TranscriptCache", self._SeededCache)
        self._SeededCache.store = {
            ("dQw4w9WgXcQ", "default"): [
                {"text": "FromCache", "start": 0.0, "duration": 1.0}
            ]
        }
        self._SeededCache.constructions = 0

    @patch("cli.single_video.YouTubeTranscriptApi")
    def test_single_video_served_from_cache(self, mock_api, capsys):
        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "-f", "text"]):
            main()

        mock_api.get_transcript.assert_not_called()
        assert "FromCache" in capsys.readouterr().out

    @patch("cli.single_video.YouTubeTranscriptApi")
    def test_no_cache_fetches_fresh(self, mock_api, capsys):
        mock_api.get_transcript.return_value = [
            {"text": "Fresh", "start": 0.0, "duration": 1.0}
        ]

        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "-f", "text", "--no-cache"]):
            main()

        mock_api.get_transcript.assert_called_once()
        assert self._SeededCache.constructions == 0
        assert "Fresh" in capsys.readouterr().out

    @patch("cli.channel_downloader.get_channel_video_ids")
    @patch("cli.channel_downloader.YouTubeTranscriptApi")
    def test_channel_mode_served_from_cache(self, mock_api, mock_get_ids, tmp_path):
        mock_get_ids.return_value = ["dQw4w9WgXcQ"]

        out_dir = str(tmp_path / "channel-out")
        with patch("sys.argv", ["cli.py", "@MrBeast", "-o", out_dir, "-f", "text"]):
            main()

        mock_api.get_transcript.assert_not_called()
        cached_file = os.path.join(out_dir, "1_dQw4w9WgXcQ.txt")
        with open(cached_file, "r", encoding="utf-8") as f:
            assert "FromCache" in f.read()


class TestTranslateFlag:
    @staticmethod
    def _mock_translator(mock_translator_cls, result="Merhaba"):
        mock_translator = MagicMock()
        mock_translator.set_lang.return_value = mock_translator
        mock_translator.set_type.return_value = mock_translator
        mock_translator.translate_transcript.return_value = result
        mock_translator_cls.return_value = mock_translator
        return mock_translator

    @patch("cli.translate.AITranscriptTranslator")
    def test_translate_happy_path(self, mock_translator_cls, monkeypatch, capsys):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        mock_translator = self._mock_translator(mock_translator_cls)

        with patch(
            "sys.argv",
            [
                "cli.py",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "--translate",
                "Turkish",
                "-l",
                "de",
            ],
        ):
            main()

        mock_translator_cls.assert_called_once_with("test-key")
        mock_translator.set_lang.assert_called_once_with("Turkish")
        mock_translator.set_type.assert_called_once_with("txt")
        mock_translator.translate_transcript.assert_called_once_with(
            "dQw4w9WgXcQ", languages=["de"]
        )
        assert "Merhaba" in capsys.readouterr().out

    @patch("cli.translate.AITranscriptTranslator")
    def test_translate_json_format(self, mock_translator_cls, monkeypatch, capsys):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        mock_translator = self._mock_translator(mock_translator_cls, result="{}")

        with patch(
            "sys.argv",
            ["cli.py", "dQw4w9WgXcQ", "--translate", "Turkish", "-f", "json"],
        ):
            main()

        mock_translator.set_type.assert_called_once_with("json")

    @patch("cli.translate.AITranscriptTranslator")
    def test_translate_failure_exits_user_error(self, mock_translator_cls, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        mock_translator = self._mock_translator(mock_translator_cls)
        mock_translator.translate_transcript.side_effect = Exception("Gemini blew up")

        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "--translate", "Turkish"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1

    def test_translate_without_api_key_exits(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with patch("sys.argv", ["cli.py", "dQw4w9WgXcQ", "--translate", "Turkish"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1

    def test_translate_rejects_srt(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with patch(
            "sys.argv",
            ["cli.py", "dQw4w9WgXcQ", "--translate", "Turkish", "-f", "srt"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1

    def test_translate_rejects_channel_mode(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        with patch("sys.argv", ["cli.py", "@MrBeast", "--translate", "Turkish"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
