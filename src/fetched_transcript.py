from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
from xml.etree.ElementTree import XMLParser

import requests

from exceptions import (
    NotTranslatable,
    TooManyRequests,
    TranscriptRetrievalError,
    TranslationLanguageNotAvailable,
)
from utils.retry import retry

_PATTERN_HTML_TAGS = re.compile(r"<[^>]+>")


class FetchedTranscript:
    """A single transcript entry that can be fetched on demand."""

    def __init__(
        self,
        video_id: str,
        language_code: str,
        language: str,
        url: str,
        is_generated: bool,
        is_translatable: bool,
        translation_languages: list[dict[str, str]],
        proxies: dict | None = None,
        cookies: str | None = None,
    ) -> None:
        self.video_id = video_id
        self.language_code = language_code
        self.language = language
        self.url = url
        self.is_generated = is_generated
        self.is_translatable = is_translatable
        self.translation_languages = translation_languages
        self._proxies = proxies
        self._cookies = cookies
        self._fetched_data: str | None = None

    @retry(
        max_attempts=3,
        backoff_factor=1.5,
        jitter=True,
        exceptions=(requests.exceptions.Timeout, requests.exceptions.ConnectionError),
    )
    def _fetch_raw(self):
        from youtube_transcript import YouTubeTranscriptApi

        headers = {"Cookie": self._cookies} if self._cookies else {}
        kwargs: dict = {"headers": headers, "timeout": 30}
        if self._proxies:
            kwargs["proxies"] = self._proxies
        return YouTubeTranscriptApi.get_session().get(self.url, **kwargs)

    def fetch(
        self,
        preserve_formatting: bool = False,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> list[dict]:
        """Download and parse the transcript. Honors HTTP 429 with backoff."""
        if self._fetched_data is not None:
            return self._process_transcript_data(self._fetched_data, preserve_formatting)

        last_exception: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                response = self._fetch_raw()
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exception = TranscriptRetrievalError(
                    self.video_id,
                    f"Network error for language {self.language_code}: {e}",
                )
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                raise last_exception
            except Exception as e:
                raise TranscriptRetrievalError(
                    self.video_id,
                    f"Failed to fetch transcript for language {self.language_code}: {e}",
                )

            if response.status_code == 429:
                if attempt < max_retries:
                    time.sleep(retry_delay * (2**attempt))
                    continue
                raise TooManyRequests(self.video_id)

            if response.status_code != 200:
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                raise TranscriptRetrievalError(
                    self.video_id,
                    f"Failed to fetch transcript: HTTP {response.status_code}",
                )

            self._fetched_data = response.text
            return self._process_transcript_data(self._fetched_data, preserve_formatting)

        raise last_exception or TranscriptRetrievalError(
            self.video_id,
            f"Failed to fetch transcript for language {self.language_code} after all retries",
        )

    def _process_transcript_data(
        self, xml_data: str, preserve_formatting: bool = False
    ) -> list[dict]:
        if not xml_data or not xml_data.strip():
            return []

        try:
            parser = XMLParser()
            parser.feed(xml_data)
            root = parser.close()
        except Exception:
            try:
                return self._process_json_transcript_data(
                    json.loads(xml_data), preserve_formatting
                )
            except (json.JSONDecodeError, Exception):
                return []

        # Prefer srv3: <p t="ms" d="ms">…</p>
        p_elements = root.findall(".//p")
        if p_elements:
            return [
                entry
                for entry in (
                    self._parse_p_element(p, preserve_formatting) for p in p_elements
                )
                if entry is not None
            ]

        # Legacy: <text start="s" dur="s">…</text>
        return [
            entry
            for entry in (
                self._parse_text_element(t, preserve_formatting)
                for t in root.findall(".//text")
            )
            if entry is not None
        ]

    @classmethod
    def _parse_p_element(cls, element, preserve_formatting: bool) -> dict | None:
        t_attr = element.get("t")
        if t_attr is None:
            return None
        start = float(t_attr) / 1000.0
        d_attr = element.get("d")
        duration = float(d_attr) / 1000.0 if d_attr else 0.0

        text = element.text or ""
        for child in element:
            if child.text:
                text += child.text
            if child.tail:
                text += child.tail

        text = cls._clean_text(text, preserve_formatting)
        if not text:
            return None
        return {"text": text, "start": start, "duration": duration}

    @classmethod
    def _parse_text_element(cls, element, preserve_formatting: bool) -> dict | None:
        text = cls._clean_text(element.text or "", preserve_formatting)
        if not text:
            return None
        return {
            "text": text,
            "start": float(element.get("start", 0)),
            "duration": float(element.get("dur", 0)),
        }

    @staticmethod
    def _clean_text(text: str, preserve_formatting: bool) -> str:
        if not preserve_formatting:
            text = _PATTERN_HTML_TAGS.sub("", text)
            text = html.unescape(text)
        return text.strip()

    def _process_json_transcript_data(
        self, json_data: dict, preserve_formatting: bool = False
    ) -> list[dict]:
        entries: list[dict] = []
        for event in json_data.get("events", []):
            segments = event.get("segs")
            if not segments:
                continue
            combined = "".join(seg.get("utf8", "") for seg in segments)
            if not combined.strip():
                continue
            entries.append(
                {
                    "text": self._clean_text(combined, preserve_formatting),
                    "start": event.get("tStartMs", 0) / 1000.0,
                    "duration": event.get("dDurationMs", 0) / 1000.0,
                }
            )
        return entries

    def translate(self, target_language_code: str) -> "FetchedTranscript":
        """Return a new FetchedTranscript for the translated version."""
        if not self.is_translatable:
            raise NotTranslatable(self.video_id, self.language_code)

        available = [lang["language_code"] for lang in self.translation_languages]
        if target_language_code not in available:
            raise TranslationLanguageNotAvailable(
                self.video_id, target_language_code, available
            )

        info = next(
            lang for lang in self.translation_languages
            if lang["language_code"] == target_language_code
        )

        return FetchedTranscript(
            video_id=self.video_id,
            language_code=target_language_code,
            language=info["language"],
            url=self._create_translated_url(target_language_code),
            is_generated=True,
            is_translatable=False,
            translation_languages=[],
            proxies=self._proxies,
            cookies=self._cookies,
        )

    def _create_translated_url(self, target_language_code: str) -> str:
        parsed = urllib.parse.urlparse(self.url)
        query = urllib.parse.parse_qs(parsed.query)
        query["tlang"] = [target_language_code]
        new_query = urllib.parse.urlencode(query, doseq=True)
        return urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
        )

    def __repr__(self) -> str:
        flags = []
        if self.is_generated:
            flags.append("GENERATED")
        if self.is_translatable:
            flags.append("TRANSLATABLE")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        return (
            f"FetchedTranscript(video_id='{self.video_id}', "
            f"language_code='{self.language_code}', language='{self.language}'{suffix})"
        )
