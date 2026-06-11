from __future__ import annotations

import json
from datetime import datetime

import requests

from exceptions import TranscriptRetrievalError
from utils.retry import retry
from utils.security import validate_url
from youtube_transcript import YouTubeTranscriptApi

_MAX_CHUNK_CHARS = 12000


def _chunk_texts(texts: list[str], max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Pack entry texts into chunks of at most max_chars, split at entry boundaries.

    A single entry longer than max_chars is kept whole (never split mid-entry).
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for text in texts:
        extra = len(text) + (1 if current else 0)
        if current and current_len + extra > max_chars:
            chunks.append(" ".join(current))
            current = [text]
            current_len = len(text)
        else:
            current.append(text)
            current_len += extra

    if current:
        chunks.append(" ".join(current))
    return chunks


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
        languages: list[str] | None = None,
    ) -> str:
        """Extract a transcript and translate it via Gemini.

        Long transcripts are split into chunks at entry boundaries and
        translated chunk by chunk to stay under model output limits.
        """
        self._current_video_id = video_id
        target_lang = target_language or self.target_language
        output_fmt = (output_type or self.output_type).lower()

        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
        except TranscriptRetrievalError:
            raise  # keep the typed error so CLI exit-code mapping holds
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

        chunks = _chunk_texts(
            [entry["text"] for entry in transcript], max_chars=_MAX_CHUNK_CHARS
        )
        translated_text = " ".join(
            self._translate_with_gemini(chunk, target_lang, custom_prompt)
            for chunk in chunks
        )
        return self._format_output(translated_text, transcript, output_fmt)

    @retry(
        max_attempts=3,
        backoff_factor=1.5,
        jitter=True,
        exceptions=(requests.exceptions.RequestException,),
    )
    def _call_gemini_api(self, url: str, headers: dict, data: dict):
        validate_url(url)
        response = requests.post(url, headers=headers, json=data, timeout=30)
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

        # requests.RequestException propagates unwrapped so the CLI maps it to exit 2.
        response = self._call_gemini_api(url, headers, payload)

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


def quick_translate(
    video_id: str,
    api_key: str,
    target_language: str = "Turkish",
    output_type: str = "txt",
) -> str:
    translator = AITranscriptTranslator(api_key)
    return (
        translator.set_lang(target_language)
        .set_type(output_type)
        .translate_transcript(video_id)
    )
