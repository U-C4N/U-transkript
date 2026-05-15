from __future__ import annotations

import json
from datetime import datetime

import requests

from utils.retry import retry
from utils.security import validate_url
from youtube_transcript import YouTubeTranscriptApi


class AITranscriptTranslator:
    """Translate YouTube transcripts using the Google Gemini API."""

    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    _DEFAULT_MODEL = "gemini-2.5-flash"
    _DEFAULT_PROMPT = (
        "Please translate the following text to {language}. "
        "Maintain the natural flow and context of the content. "
        "Only return the translated text without any additional comments or explanations.\n\n"
        "Text to translate:\n{text}"
    )

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = self._BASE_URL
        self.target_language: str = "English"
        self.output_type: str = "txt"
        self._current_video_id: str = "unknown"

    def set_model(self, model_name: str) -> "AITranscriptTranslator":
        self.model = model_name
        return self

    def set_api(self, api_key: str) -> "AITranscriptTranslator":
        self.api_key = api_key
        return self

    def set_lang(self, target_language: str) -> "AITranscriptTranslator":
        self.target_language = target_language
        return self

    def set_type(self, output_type: str) -> "AITranscriptTranslator":
        self.output_type = output_type.lower()
        return self

    def translate_transcript(
        self,
        video_id: str,
        target_language: str | None = None,
        output_type: str | None = None,
        custom_prompt: str | None = None,
    ) -> str:
        """Extract a transcript and translate it via Gemini."""
        self._current_video_id = video_id
        target_lang = target_language or self.target_language
        output_fmt = (output_type or self.output_type).lower()

        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
        except Exception as e:
            raise Exception(
                f"Failed to extract or validate transcript for video_id '{video_id}': {e}"
            )

        if not isinstance(transcript, list) or not all(
            isinstance(item, dict) and "text" in item for item in transcript
        ):
            raise Exception(
                f"Failed to extract or validate transcript for video_id '{video_id}': "
                f"Unexpected transcript data format: {type(transcript)}"
            )

        full_text = " ".join(entry["text"] for entry in transcript)
        translated_text = self._translate_with_gemini(full_text, target_lang, custom_prompt)
        return self._format_output(translated_text, transcript, output_fmt)

    @retry(
        max_attempts=3,
        backoff_factor=1.5,
        jitter=True,
        exceptions=(requests.exceptions.RequestException,),
    )
    def _call_gemini_api(self, url: str, headers: dict, data: dict):
        validate_url(url)
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response

    def _translate_with_gemini(
        self, text: str, target_language: str, custom_prompt: str | None = None
    ) -> str:
        prompt_template = custom_prompt or self._DEFAULT_PROMPT
        prompt = prompt_template.format(text=text, language=target_language)

        url = f"{self.base_url}/{self.model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        try:
            response = self._call_gemini_api(url, headers, payload)
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {e}")

        try:
            result = response.json()
            return result["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, ValueError) as e:
            raise Exception(f"Translation failed: Invalid response format from Gemini API ({e})")

    def _format_output(
        self, translated_text: str, original_transcript: list[dict], output_type: str
    ) -> str:
        if output_type == "txt":
            return translated_text
        if output_type == "json":
            return self._render_json(translated_text, original_transcript)
        if output_type == "xml":
            return self._render_xml(translated_text, original_transcript)
        raise ValueError(f"Unsupported output type: {output_type}")

    def _render_json(self, translated_text: str, original_transcript: list[dict]) -> str:
        payload = {
            "video_id": self._current_video_id,
            "target_language": self.target_language,
            "original_transcript": original_transcript,
            "translated_text": translated_text,
            "translation_metadata": {
                "model": self.model,
                "timestamp": self._get_current_timestamp(),
            },
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _render_xml(self, translated_text: str, original_transcript: list[dict]) -> str:
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<transcript>",
            "    <metadata>",
            f"        <video_id>{self._current_video_id}</video_id>",
            f"        <target_language>{self.target_language}</target_language>",
            f"        <model>{self.model}</model>",
            f"        <timestamp>{self._get_current_timestamp()}</timestamp>",
            "    </metadata>",
            "    <original_transcript>",
        ]
        for entry in original_transcript:
            parts.append(
                f'        <entry start="{entry["start"]}" duration="{entry["duration"]}">'
            )
            parts.append(f"            <text>{self._escape_xml(entry['text'])}</text>")
            parts.append("        </entry>")
        parts.extend(
            [
                "    </original_transcript>",
                "    <translated_text>",
                f"        <![CDATA[{translated_text}]]>",
                "    </translated_text>",
                "</transcript>",
            ]
        )
        return "\n".join(parts)

    @staticmethod
    def _get_current_timestamp() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _escape_xml(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )
