import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from ai_translator import AITranscriptTranslator


class TestAITranslatorInit:
    def test_init_with_api_key(self):
        translator = AITranscriptTranslator("test-api-key")
        assert translator.api_key == "test-api-key"
        assert translator.model == "gemini-2.5-flash"

    def test_init_with_custom_model(self):
        translator = AITranscriptTranslator("test-api-key", model="gemini-pro")
        assert translator.model == "gemini-pro"

    def test_base_url(self):
        translator = AITranscriptTranslator("test-api-key")
        assert "generativelanguage.googleapis.com" in translator.base_url


class TestMethodChaining:
    def test_set_model_returns_self(self):
        translator = AITranscriptTranslator("test-api-key")
        result = translator.set_model("gemini-pro")
        assert result is translator
        assert translator.model == "gemini-pro"

    def test_set_lang_returns_self(self):
        translator = AITranscriptTranslator("test-api-key")
        result = translator.set_lang("Turkish")
        assert result is translator
        assert translator.target_language == "Turkish"

    def test_set_type_returns_self(self):
        translator = AITranscriptTranslator("test-api-key")
        result = translator.set_type("json")
        assert result is translator
        assert translator.output_type == "json"

    def test_set_type_lowercases(self):
        translator = AITranscriptTranslator("test-api-key")
        translator.set_type("JSON")
        assert translator.output_type == "json"

    def test_set_api_returns_self(self):
        translator = AITranscriptTranslator("test-api-key")
        result = translator.set_api("new-key")
        assert result is translator
        assert translator.api_key == "new-key"

    def test_full_chain(self):
        translator = AITranscriptTranslator("test-api-key")
        result = (
            translator.set_model("gemini-pro")
            .set_lang("Turkish")
            .set_type("json")
            .set_api("new-key")
        )
        assert result is translator
        assert translator.model == "gemini-pro"
        assert translator.target_language == "Turkish"
        assert translator.output_type == "json"
        assert translator.api_key == "new-key"


class TestFormatOutput:
    def setup_method(self):
        self.translator = AITranscriptTranslator("test-api-key")
        self.transcript = [
            {"text": "Hello world", "start": 0.0, "duration": 2.5},
            {"text": "This is a test", "start": 2.5, "duration": 3.0},
        ]

    def test_format_txt(self):
        result = self.translator._format_output(
            "Merhaba dünya", self.transcript, "txt"
        )
        assert result == "Merhaba dünya"

    def test_format_json(self):
        self.translator.target_language = "Turkish"
        result = self.translator._format_output(
            "Merhaba dünya", self.transcript, "json"
        )
        parsed = json.loads(result)
        assert "translated_text" in parsed
        assert parsed["translated_text"] == "Merhaba dünya"
        assert "original_transcript" in parsed
        assert "translation_metadata" in parsed
        assert parsed["translation_metadata"]["model"] == "gemini-2.5-flash"

    def test_format_xml(self):
        self.translator.target_language = "Turkish"
        result = self.translator._format_output(
            "Merhaba dünya", self.transcript, "xml"
        )
        assert '<?xml version="1.0"' in result
        assert "<transcript>" in result
        assert "<translated_text>" in result
        assert "Merhaba dünya" in result
        assert "<entry" in result

    def test_format_invalid_raises(self):
        with pytest.raises(ValueError, match="Unsupported output type"):
            self.translator._format_output("text", self.transcript, "csv")


class TestEscapeXml:
    def setup_method(self):
        self.translator = AITranscriptTranslator("test-api-key")

    def test_escape_ampersand(self):
        assert "&amp;" in self.translator._escape_xml("a & b")

    def test_escape_less_than(self):
        assert "&lt;" in self.translator._escape_xml("a < b")

    def test_escape_greater_than(self):
        assert "&gt;" in self.translator._escape_xml("a > b")

    def test_escape_double_quote(self):
        assert "&quot;" in self.translator._escape_xml('a "b" c')

    def test_escape_single_quote(self):
        assert "&#39;" in self.translator._escape_xml("a 'b' c")

    def test_no_escaping_needed(self):
        assert self.translator._escape_xml("plain text") == "plain text"

    def test_multiple_escapes(self):
        result = self.translator._escape_xml('<a & "b">')
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&quot;" in result
        assert "&gt;" in result


class TestGetCurrentTimestamp:
    def test_returns_iso_format(self):
        translator = AITranscriptTranslator("test-api-key")
        ts = translator._get_current_timestamp()
        # Should be parseable as ISO format
        datetime.fromisoformat(ts)

    def test_timestamp_is_recent(self):
        translator = AITranscriptTranslator("test-api-key")
        ts = translator._get_current_timestamp()
        parsed = datetime.fromisoformat(ts)
        now = datetime.now()
        # Should be within a few seconds
        diff = abs((now - parsed).total_seconds())
        assert diff < 5


class TestTranslateWithGemini:
    def test_successful_translation(self, mock_gemini_response):
        translator = AITranscriptTranslator("test-api-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_gemini_response
        mock_response.raise_for_status = MagicMock()

        with patch("ai_translator.requests.post", return_value=mock_response):
            result = translator._translate_with_gemini("Hello world", "Turkish")
            assert "Merhaba" in result

    def test_api_error_raises(self):
        translator = AITranscriptTranslator("test-api-key")

        import requests

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = (
            requests.exceptions.HTTPError("403 Forbidden")
        )

        with patch("ai_translator.requests.post", return_value=mock_response):
            with pytest.raises(Exception, match="API request failed"):
                translator._translate_with_gemini("Hello", "Turkish")

    def test_invalid_response_format(self):
        translator = AITranscriptTranslator("test-api-key")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"candidates": []}

        with patch("ai_translator.requests.post", return_value=mock_response):
            with pytest.raises(Exception, match="Translation failed"):
                translator._translate_with_gemini("Hello", "Turkish")

    def test_custom_prompt(self, mock_gemini_response):
        translator = AITranscriptTranslator("test-api-key")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_gemini_response

        with patch("ai_translator.requests.post", return_value=mock_response) as mock_post:
            translator._translate_with_gemini(
                "Hello",
                "Turkish",
                custom_prompt="Translate '{text}' to {language}",
            )
            # Verify the custom prompt was used in the request
            call_args = mock_post.call_args
            sent_data = call_args[1]["json"]
            prompt_text = sent_data["contents"][0]["parts"][0]["text"]
            assert "Translate 'Hello' to Turkish" == prompt_text


class TestTranslateTranscript:
    @patch.object(AITranscriptTranslator, "_translate_with_gemini")
    @patch("ai_translator.YouTubeTranscriptApi.get_transcript")
    def test_translate_transcript_success(self, mock_get, mock_translate):
        mock_get.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 1.0},
            {"text": "World", "start": 1.0, "duration": 1.0},
        ]
        mock_translate.return_value = "Merhaba Dünya"

        translator = AITranscriptTranslator("test-api-key")
        result = translator.translate_transcript("test_vid", target_language="Turkish")
        assert result == "Merhaba Dünya"

    @patch("ai_translator.YouTubeTranscriptApi.get_transcript")
    def test_translate_transcript_extraction_failure(self, mock_get):
        mock_get.side_effect = Exception("Video not found")

        translator = AITranscriptTranslator("test-api-key")
        with pytest.raises(Exception, match="Failed to extract"):
            translator.translate_transcript("bad_vid")
