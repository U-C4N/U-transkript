import pytest
from unittest.mock import patch, MagicMock
import json

from youtube_transcript import YouTubeTranscriptApi
from transcript_list import TranscriptList
from exceptions import (
    VideoUnavailable,
    TranscriptNotFound,
    TooManyRequests,
    TranscriptRetrievalError,
    NoTranscriptFound,
)


class TestGetTranscript:
    @patch.object(YouTubeTranscriptApi, "list_transcripts")
    def test_get_transcript_success(self, mock_list):
        """Test successful transcript retrieval."""
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 1.0}
        ]
        mock_transcript.is_translatable = False

        mock_tl = MagicMock(spec=TranscriptList)
        mock_tl.find_transcript.return_value = mock_transcript
        mock_tl.find_generated_transcript.return_value = mock_transcript
        mock_list.return_value = mock_tl

        result = YouTubeTranscriptApi.get_transcript("test123", languages=["en"])
        assert len(result) == 1
        assert result[0]["text"] == "Hello"

    @patch.object(YouTubeTranscriptApi, "list_transcripts")
    def test_get_transcript_language_fallback(self, mock_list):
        """Test that it falls back to the next language when the first is not found."""
        mock_transcript_tr = MagicMock()
        mock_transcript_tr.fetch.return_value = [
            {"text": "Merhaba", "start": 0.0, "duration": 1.0}
        ]

        mock_tl = MagicMock(spec=TranscriptList)
        # First language raises, second succeeds
        mock_tl.find_transcript.side_effect = [
            NoTranscriptFound("test123", ["en"], {}),
            mock_transcript_tr,
        ]
        mock_list.return_value = mock_tl

        result = YouTubeTranscriptApi.get_transcript("test123", languages=["en", "tr"])
        assert result[0]["text"] == "Merhaba"

    @patch.object(YouTubeTranscriptApi, "list_transcripts")
    def test_get_transcript_default_language(self, mock_list):
        """Test that it defaults to English when no language is specified."""
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 1.0}
        ]

        mock_tl = MagicMock(spec=TranscriptList)
        mock_tl.find_generated_transcript.return_value = mock_transcript
        mock_list.return_value = mock_tl

        result = YouTubeTranscriptApi.get_transcript("test123")
        assert result[0]["text"] == "Hello"
        mock_tl.find_generated_transcript.assert_called_with(["en"])


class TestListTranscripts:
    @patch.object(YouTubeTranscriptApi, "_fetch_video_page")
    def test_video_not_found_404(self, mock_fetch):
        """Test that a 404 response raises VideoUnavailable."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_fetch.return_value = mock_response

        with pytest.raises(VideoUnavailable):
            YouTubeTranscriptApi.list_transcripts("nonexistent_video", max_retries=0)

    @patch.object(YouTubeTranscriptApi, "_fetch_video_page")
    def test_rate_limiting_429(self, mock_fetch):
        """Test that a 429 response raises TooManyRequests."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_fetch.return_value = mock_response

        with pytest.raises(TooManyRequests):
            YouTubeTranscriptApi.list_transcripts(
                "test123", max_retries=0, retry_delay=0
            )

    @patch.object(YouTubeTranscriptApi, "_fetch_video_page")
    def test_network_error(self, mock_fetch):
        """Test that network errors are handled properly."""
        import requests

        mock_fetch.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )

        with pytest.raises((TranscriptRetrievalError, Exception)):
            YouTubeTranscriptApi.list_transcripts(
                "test123", max_retries=0, retry_delay=0
            )

    @patch.object(YouTubeTranscriptApi, "_fetch_video_page")
    def test_timeout_error(self, mock_fetch):
        """Test that timeout errors are handled properly."""
        import requests

        mock_fetch.side_effect = requests.exceptions.Timeout("Request timed out")

        with pytest.raises((TranscriptRetrievalError, Exception)):
            YouTubeTranscriptApi.list_transcripts(
                "test123", max_retries=0, retry_delay=0
            )

    @patch.object(YouTubeTranscriptApi, "_fetch_video_page")
    def test_successful_list_transcripts(self, mock_fetch, mock_youtube_html):
        """Test successful listing of transcripts from HTML."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = mock_youtube_html
        mock_fetch.return_value = mock_response

        # Also mock the Innertube API call to return None so it falls back to HTML
        with patch.object(
            YouTubeTranscriptApi, "_extract_innertube_api_key", return_value=None
        ):
            result = YouTubeTranscriptApi.list_transcripts("test123", max_retries=0)
            assert isinstance(result, TranscriptList)


class TestGetTranscripts:
    @patch.object(YouTubeTranscriptApi, "get_transcript")
    def test_multiple_videos(self, mock_get):
        mock_get.return_value = [{"text": "Hello", "start": 0.0, "duration": 1.0}]
        results = YouTubeTranscriptApi.get_transcripts(["vid1", "vid2"])
        assert len(results) == 2
        assert results[0]["video_id"] == "vid1"
        assert results[1]["video_id"] == "vid2"

    @patch.object(YouTubeTranscriptApi, "get_transcript")
    def test_continue_on_failure(self, mock_get):
        mock_get.side_effect = [
            TranscriptRetrievalError("vid1", "Error"),
            [{"text": "Hello", "start": 0.0, "duration": 1.0}],
        ]
        results = YouTubeTranscriptApi.get_transcripts(
            ["vid1", "vid2"], continue_on_failure=True
        )
        assert len(results) == 2
        assert results[0]["error"] is not None
        assert results[0]["transcript"] is None
        assert results[1]["transcript"] is not None

    @patch.object(YouTubeTranscriptApi, "get_transcript")
    def test_stop_on_failure(self, mock_get):
        mock_get.side_effect = TranscriptRetrievalError("vid1", "Error")
        with pytest.raises(TranscriptRetrievalError):
            YouTubeTranscriptApi.get_transcripts(
                ["vid1", "vid2"], continue_on_failure=False
            )


class TestExtractTranscriptData:
    def test_extract_from_yt_initial_player_response(self, mock_youtube_html):
        """Test extraction from ytInitialPlayerResponse pattern."""
        with patch.object(
            YouTubeTranscriptApi, "_extract_innertube_api_key", return_value=None
        ):
            result = YouTubeTranscriptApi._extract_transcript_data(
                mock_youtube_html, "test123"
            )
            assert isinstance(result, dict)
            assert "en" in result
            assert "tr" in result

    def test_extract_empty_html(self):
        """Test extraction from empty HTML returns empty dict."""
        with patch.object(
            YouTubeTranscriptApi, "_extract_innertube_api_key", return_value=None
        ):
            result = YouTubeTranscriptApi._extract_transcript_data("", "test123")
            assert result == {}

    def test_find_captions_data_nested(self):
        """Test _find_captions_data finds data in nested dicts."""
        data = {
            "captions": {
                "playerCaptionsTracklistRenderer": {
                    "captionTracks": [{"languageCode": "en"}]
                }
            }
        }
        result = YouTubeTranscriptApi._find_captions_data(data)
        assert result is not None
        assert "captionTracks" in result

    def test_find_captions_data_none_for_empty(self):
        result = YouTubeTranscriptApi._find_captions_data({})
        assert result is None

    def test_find_captions_data_in_list(self):
        data = [
            {"playerCaptionsTracklistRenderer": {"captionTracks": []}}
        ]
        result = YouTubeTranscriptApi._find_captions_data(data)
        assert result is not None
