from __future__ import annotations

import re
import html
import json
import requests
import urllib.parse
from xml.etree.ElementTree import XMLParser

from exceptions import (
    TranscriptRetrievalError,
    NotTranslatable,
    TranslationLanguageNotAvailable,
    TooManyRequests
)
from utils.retry import retry

# Pre-compiled pattern for HTML tag removal
_PATTERN_HTML_TAGS = re.compile(r'<[^>]+>')


class FetchedTranscript:
    """
    Represents a single transcript that can be fetched and formatted.
    """

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
        cookies: str | None = None
    ):
        """
        Initialize FetchedTranscript.

        Args:
            video_id: YouTube video ID
            language_code: Language code (e.g., 'en', 'es')
            language: Human-readable language name
            url: URL to fetch transcript data
            is_generated: Whether this is an auto-generated transcript
            is_translatable: Whether this transcript can be translated
            translation_languages: List of available translation languages
            proxies: Proxy configuration for requests
            cookies: Cookie string for authentication
        """
        self.video_id = video_id
        self.language_code = language_code
        self.language = language
        self.url = url
        self.is_generated = is_generated
        self.is_translatable = is_translatable
        self.translation_languages = translation_languages
        self._proxies = proxies
        self._cookies = cookies
        self._fetched_data = None

    @retry(
        max_attempts=3,
        backoff_factor=1.5,
        jitter=True,
        exceptions=(requests.exceptions.Timeout, requests.exceptions.ConnectionError),
    )
    def _fetch_raw(self):
        """Fetch raw transcript data from URL with retry for transient errors."""
        from youtube_transcript import YouTubeTranscriptApi
        session = YouTubeTranscriptApi.get_session()

        headers = {}
        if self._cookies:
            headers['Cookie'] = self._cookies

        kwargs = {'headers': headers, 'timeout': 30}
        if self._proxies:
            kwargs['proxies'] = self._proxies

        return session.get(self.url, **kwargs)

    def fetch(self, preserve_formatting: bool = False, max_retries: int = 3, retry_delay: float = 1.0) -> list[dict]:
        """
        Fetch the transcript data.

        Args:
            preserve_formatting: Whether to preserve HTML formatting in text
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds

        Returns:
            List of transcript entries with 'text', 'start', and 'duration' keys
        """
        if self._fetched_data is not None:
            return self._process_transcript_data(self._fetched_data, preserve_formatting)

        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                response = self._fetch_raw()

                if response.status_code == 429:
                    if attempt < max_retries:
                        import time
                        time.sleep(retry_delay * (2 ** attempt))
                        continue
                    raise TooManyRequests(self.video_id)
                elif response.status_code != 200:
                    if attempt < max_retries:
                        import time
                        time.sleep(retry_delay)
                        continue
                    raise TranscriptRetrievalError(
                        self.video_id,
                        f"Failed to fetch transcript: HTTP {response.status_code}"
                    )

                self._fetched_data = response.text
                return self._process_transcript_data(self._fetched_data, preserve_formatting)

            except TooManyRequests:
                raise
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exception = TranscriptRetrievalError(
                    self.video_id,
                    f"Network error for language {self.language_code}: {str(e)}"
                )
                if attempt < max_retries:
                    import time
                    time.sleep(retry_delay)
                    continue
            except Exception as e:
                last_exception = TranscriptRetrievalError(
                    self.video_id,
                    f"Failed to fetch transcript for language {self.language_code}: {str(e)}"
                )
                if attempt < max_retries:
                    import time
                    time.sleep(retry_delay)
                    continue

        raise last_exception or TranscriptRetrievalError(
            self.video_id,
            f"Failed to fetch transcript for language {self.language_code} after all retries"
        )

    def _process_transcript_data(self, xml_data: str, preserve_formatting: bool = False) -> list[dict]:
        """
        Process XML transcript data into structured format.

        Args:
            xml_data: Raw XML transcript data
            preserve_formatting: Whether to preserve HTML formatting

        Returns:
            List of transcript entries
        """
        if not xml_data or not xml_data.strip():
            return []

        try:
            # XXE-safe XML parsing
            parser = XMLParser()
            parser.feed(xml_data)
            root = parser.close()

            transcript_entries = []

            # Try srv3 format first: <p t="ms" d="ms">text</p>
            p_elements = root.findall('.//p')
            if p_elements:
                for p_element in p_elements:
                    t_attr = p_element.get('t')
                    d_attr = p_element.get('d')
                    if t_attr is None:
                        continue

                    # srv3 format uses milliseconds
                    start = float(t_attr) / 1000.0
                    duration = float(d_attr) / 1000.0 if d_attr else 0.0

                    # Text content: direct text + nested <s> segments
                    text_content = p_element.text or ''
                    for child in p_element:
                        if child.text:
                            text_content += child.text
                        if child.tail:
                            text_content += child.tail

                    if not preserve_formatting:
                        text_content = _PATTERN_HTML_TAGS.sub('', text_content)
                        text_content = html.unescape(text_content)

                    text_content = text_content.strip()

                    if text_content:
                        transcript_entries.append({
                            'text': text_content,
                            'start': start,
                            'duration': duration
                        })

                return transcript_entries

            # Fallback: legacy format <text start="s" dur="s">text</text>
            for text_element in root.findall('.//text'):
                start = float(text_element.get('start', 0))
                duration = float(text_element.get('dur', 0))

                text_content = text_element.text or ''

                if not preserve_formatting:
                    text_content = _PATTERN_HTML_TAGS.sub('', text_content)
                    text_content = html.unescape(text_content)

                text_content = text_content.strip()

                if text_content:
                    transcript_entries.append({
                        'text': text_content,
                        'start': start,
                        'duration': duration
                    })

            return transcript_entries

        except Exception:
            # If XML parsing fails, try to handle as JSON
            try:
                data = json.loads(xml_data)
                return self._process_json_transcript_data(data, preserve_formatting)
            except (json.JSONDecodeError, Exception):
                return []

    def _process_json_transcript_data(self, json_data: dict, preserve_formatting: bool = False) -> list[dict]:
        """
        Process JSON transcript data (alternative format).
        """
        transcript_entries = []

        events = json_data.get('events', [])

        for event in events:
            if 'segs' in event:
                start_time = event.get('tStartMs', 0) / 1000.0
                text_segments = event['segs']

                # Use list append + join instead of string concatenation
                parts = []
                for segment in text_segments:
                    if 'utf8' in segment:
                        parts.append(segment['utf8'])
                combined_text = ''.join(parts)

                if combined_text.strip():
                    if not preserve_formatting:
                        combined_text = _PATTERN_HTML_TAGS.sub('', combined_text)
                        combined_text = html.unescape(combined_text)

                    transcript_entries.append({
                        'text': combined_text.strip(),
                        'start': start_time,
                        'duration': event.get('dDurationMs', 0) / 1000.0
                    })

        return transcript_entries

    def translate(self, target_language_code: str) -> FetchedTranscript:
        """
        Create a translated version of this transcript.

        Args:
            target_language_code: Target language code for translation

        Returns:
            New FetchedTranscript object for the translated version

        Raises:
            NotTranslatable: If this transcript cannot be translated
            TranslationLanguageNotAvailable: If target language is not available
        """
        if not self.is_translatable:
            raise NotTranslatable(self.video_id, self.language_code)

        available_languages = [lang['language_code'] for lang in self.translation_languages]
        if target_language_code not in available_languages:
            raise TranslationLanguageNotAvailable(
                self.video_id,
                target_language_code,
                available_languages
            )

        target_language_info = None
        for lang in self.translation_languages:
            if lang['language_code'] == target_language_code:
                target_language_info = lang
                break

        if not target_language_info:
            raise TranslationLanguageNotAvailable(
                self.video_id,
                target_language_code,
                available_languages
            )

        translated_url = self._create_translated_url(target_language_code)

        return FetchedTranscript(
            video_id=self.video_id,
            language_code=target_language_code,
            language=target_language_info['language'],
            url=translated_url,
            is_generated=True,
            is_translatable=False,
            translation_languages=[],
            proxies=self._proxies,
            cookies=self._cookies
        )

    def _create_translated_url(self, target_language_code: str) -> str:
        """
        Create URL for translated transcript.

        Args:
            target_language_code: Target language code

        Returns:
            URL for fetching translated transcript
        """
        parsed_url = urllib.parse.urlparse(self.url)
        query_params = urllib.parse.parse_qs(parsed_url.query)

        query_params['tlang'] = [target_language_code]

        new_query = urllib.parse.urlencode(query_params, doseq=True)
        translated_url = urllib.parse.urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment
        ))

        return translated_url

    def __repr__(self):
        """
        String representation of FetchedTranscript.
        """
        status_flags = []
        if self.is_generated:
            status_flags.append("GENERATED")
        if self.is_translatable:
            status_flags.append("TRANSLATABLE")

        status_str = f" [{', '.join(status_flags)}]" if status_flags else ""

        return f"FetchedTranscript(video_id='{self.video_id}', language_code='{self.language_code}', language='{self.language}'{status_str})"
