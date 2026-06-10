from __future__ import annotations

import json
import re
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry as URLLibRetry

from exceptions import (
    NoTranscriptFound,
    TooManyRequests,
    TranscriptNotFound,
    TranscriptRetrievalError,
    VideoUnavailable,
)
from fetched_transcript import FetchedTranscript
from transcript_list import TranscriptList
from utils.retry import retry

_CAPTION_PATTERNS = [
    re.compile(r'"captions":\s*\{[^}]*"playerCaptionsTracklistRenderer":\s*(\{.*?\})'),
    re.compile(r'"playerCaptionsTracklistRenderer":\s*(\{.*?"captionTracks".*?\})'),
    re.compile(r'ytInitialPlayerResponse["\']?:\s*(\{.*?\})'),
    re.compile(r"var\s+ytInitialPlayerResponse\s*=\s*(\{.*?\});"),
    re.compile(r'"captionTracks":\s*\[(.*?)\]'),
    re.compile(r'"playerCaptionsRenderer":\s*(\{.*?\})'),
    re.compile(r'"captions":(\{.*?"playerCaptionsTracklistRenderer".*?\})'),
    re.compile(r'ytInitialPlayerResponse":\s*(\{.*?\})\s*[,}]'),
]

_INNERTUBE_API_KEY_PATTERNS = [
    re.compile(r'"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"'),
    re.compile(r'"innertubeApiKey":\s*"([a-zA-Z0-9_-]+)"'),
    re.compile(r'"apiKey":\s*"([a-zA-Z0-9_-]+)"'),
]

_PATTERN_TIMEDTEXT = re.compile(
    r'["\']timedtext["\'].*?["\']([^"\']*)["\']', re.IGNORECASE
)


class YouTubeTranscriptApi:
    """Main entry point for retrieving YouTube video transcripts."""

    _WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
    _INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/player?key={api_key}"

    _session: requests.Session | None = None

    @classmethod
    def get_session(cls) -> requests.Session:
        if cls._session is None:
            session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=URLLibRetry(total=0),
            )
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )
            cls._session = session
        return cls._session

    @classmethod
    def close_session(cls) -> None:
        if cls._session is not None:
            cls._session.close()
            cls._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_session()
        return False

    @classmethod
    def get_transcript(
        cls,
        video_id: str,
        languages: list[str] | None = None,
        proxies: dict | None = None,
        cookies: str | None = None,
        preserve_formatting: bool = False,
    ) -> list[dict]:
        """Retrieve transcript entries for a single video."""
        transcript_list = cls.list_transcripts(
            video_id, proxies=proxies, cookies=cookies
        )

        if languages:
            for language_code in languages:
                try:
                    transcript = transcript_list.find_transcript([language_code])
                    return transcript.fetch(preserve_formatting=preserve_formatting)
                except (NoTranscriptFound, TranscriptNotFound):
                    continue

            try:
                transcript = transcript_list.find_manually_created_transcript(languages)
                if transcript.is_translatable:
                    try:
                        translated = transcript.translate(languages[0])
                        return translated.fetch(preserve_formatting=preserve_formatting)
                    except Exception:
                        pass
            except (NoTranscriptFound, TranscriptNotFound):
                pass

            raise NoTranscriptFound(
                video_id, languages, getattr(transcript_list, "_transcript_data", {})
            )

        for finder in (
            transcript_list.find_generated_transcript,
            transcript_list.find_manually_created_transcript,
        ):
            try:
                return finder(["en"]).fetch(preserve_formatting=preserve_formatting)
            except NoTranscriptFound:
                continue

        data = getattr(transcript_list, "_transcript_data", {})
        for lang_key, entries in data.items():
            if not entries:
                continue
            info = entries[0]
            transcript_obj = FetchedTranscript(
                video_id=video_id,
                language_code=info["language_code"],
                language=info["language"],
                url=info["url"],
                is_generated=info["is_generated"],
                is_translatable=info["is_translatable"],
                translation_languages=info.get("translation_languages", []),
                proxies=proxies,
                cookies=cookies,
            )
            return transcript_obj.fetch(preserve_formatting=preserve_formatting)

        raise TranscriptNotFound(video_id)

    @classmethod
    def get_transcripts(
        cls,
        video_ids: list[str],
        languages: list[str] | None = None,
        proxies: dict | None = None,
        cookies: str | None = None,
        preserve_formatting: bool = False,
        continue_on_failure: bool = False,
    ) -> list[dict]:
        """Retrieve transcripts for multiple videos."""
        results: list[dict] = []

        for video_id in video_ids:
            try:
                transcript = cls.get_transcript(
                    video_id,
                    languages=languages,
                    proxies=proxies,
                    cookies=cookies,
                    preserve_formatting=preserve_formatting,
                )
                results.append({"video_id": video_id, "transcript": transcript, "error": None})
            except Exception as e:
                if not continue_on_failure:
                    raise
                results.append({"video_id": video_id, "transcript": None, "error": str(e)})

        return results

    @classmethod
    @retry(
        max_attempts=3,
        backoff_factor=1.5,
        jitter=True,
        exceptions=(requests.exceptions.Timeout, requests.exceptions.ConnectionError),
    )
    def _fetch_video_page(
        cls, watch_url: str, proxies: dict | None = None, cookies: str | None = None
    ):
        """Fetch the YouTube watch page (with @retry on transient network errors)."""
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if cookies:
            headers["Cookie"] = cookies

        kwargs: dict = {"headers": headers, "timeout": 30}
        if proxies:
            kwargs["proxies"] = proxies

        return cls.get_session().get(watch_url, **kwargs)

    @classmethod
    def list_transcripts(
        cls,
        video_id: str,
        proxies: dict | None = None,
        cookies: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> TranscriptList:
        """List all transcripts for a video. Honors HTTP 429 with exponential backoff."""
        watch_url = cls._WATCH_URL.format(video_id=video_id)
        last_exception: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                response = cls._fetch_video_page(watch_url, proxies=proxies, cookies=cookies)
            except requests.exceptions.RequestException as e:
                last_exception = TranscriptRetrievalError(
                    video_id, f"Network error: {e}"
                )
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                raise last_exception

            if response.status_code == 429:
                if attempt < max_retries:
                    time.sleep(retry_delay * (2**attempt))
                    continue
                raise TooManyRequests(video_id)
            if response.status_code == 404:
                raise VideoUnavailable(video_id)
            if response.status_code != 200:
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                raise VideoUnavailable(video_id)

            transcript_data = cls._extract_transcript_data(response.text, video_id)
            if not transcript_data:
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                raise TranscriptNotFound(video_id)

            return TranscriptList(video_id, transcript_data, proxies=proxies, cookies=cookies)

        raise last_exception or TranscriptRetrievalError(
            video_id, "Failed to retrieve transcript list after all retries"
        )

    @classmethod
    def _extract_transcript_data(cls, html_content: str, video_id: str) -> dict:
        """Extract caption track metadata from the YouTube watch page HTML."""
        try:
            api_key = cls._extract_innertube_api_key(html_content)
            if api_key:
                innertube_data = cls._fetch_innertube_data(video_id, api_key)
                if innertube_data:
                    captions_data = cls._extract_captions_from_innertube(innertube_data)
                    if captions_data:
                        return cls._parse_transcript_data(captions_data, video_id)
        except Exception:
            pass

        for pattern in _CAPTION_PATTERNS:
            match = pattern.search(html_content)
            if not match:
                continue
            try:
                data = json.loads(match.group(1))
            except (json.JSONDecodeError, KeyError):
                continue
            captions_data = cls._find_captions_data(data)
            if captions_data:
                return cls._parse_transcript_data(captions_data, video_id)

        return cls._extract_alternative_transcript_data(html_content, video_id)

    @classmethod
    def _find_captions_data(cls, data) -> dict | None:
        """Walk a nested dict/list looking for a playerCaptionsTracklistRenderer."""
        if isinstance(data, dict):
            if "playerCaptionsTracklistRenderer" in data:
                return data["playerCaptionsTracklistRenderer"]
            for key, value in data.items():
                if key == "captions" and isinstance(value, dict):
                    if "playerCaptionsTracklistRenderer" in value:
                        return value["playerCaptionsTracklistRenderer"]
                result = cls._find_captions_data(value)
                if result:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = cls._find_captions_data(item)
                if result:
                    return result
        return None

    @staticmethod
    def _read_language_name(name_data, fallback: str) -> str:
        """ANDROID InnerTube uses runs[0].text; WEB uses simpleText."""
        if isinstance(name_data, dict):
            text = name_data.get("simpleText")
            if text:
                return text
            runs = name_data.get("runs")
            if isinstance(runs, list) and runs:
                return runs[0].get("text", fallback)
            return fallback
        return str(name_data) if name_data else fallback

    @classmethod
    def _parse_transcript_data(cls, captions_data: dict, video_id: str) -> dict:
        """Convert raw captionTracks list into our internal transcript_data dict."""
        transcript_data: dict[str, list[dict]] = {}
        caption_tracks = captions_data.get("captionTracks", [])
        translation_languages = captions_data.get("translationLanguages", [])

        translations = [
            {
                "language_code": lang.get("languageCode", ""),
                "language": lang.get("languageName", {}).get("simpleText", ""),
            }
            for lang in translation_languages
        ]

        for track in caption_tracks:
            base_url = track.get("baseUrl", "")
            if not base_url:
                continue

            language_code = track.get("languageCode", "unknown")
            language_name = cls._read_language_name(track.get("name", {}), language_code)

            info = {
                "language_code": language_code,
                "language": language_name,
                "url": base_url,
                "is_generated": track.get("kind") == "asr",
                "is_translatable": bool(translation_languages),
                "translation_languages": translations,
            }
            transcript_data.setdefault(language_code, []).append(info)

        return transcript_data

    @classmethod
    def _extract_innertube_api_key(cls, html_content: str) -> str | None:
        for pattern in _INNERTUBE_API_KEY_PATTERNS:
            match = pattern.search(html_content)
            if match:
                return match.group(1)
        return None

    @classmethod
    def _fetch_innertube_data(cls, video_id: str, api_key: str) -> dict | None:
        """POST to the InnerTube API using the ANDROID client (no PoToken needed)."""
        url = cls._INNERTUBE_URL.format(api_key=api_key)
        payload = {
            "context": {
                "client": {"clientName": "ANDROID", "clientVersion": "20.10.38"}
            },
            "videoId": video_id,
        }
        try:
            response = cls.get_session().post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            return None
        return None

    @classmethod
    def _extract_captions_from_innertube(cls, innertube_data: dict) -> dict | None:
        captions = innertube_data.get("captions", {}) if isinstance(innertube_data, dict) else {}
        if isinstance(captions, dict) and "playerCaptionsTracklistRenderer" in captions:
            return captions["playerCaptionsTracklistRenderer"]
        return None

    @classmethod
    def _extract_alternative_transcript_data(cls, html_content: str, video_id: str) -> dict:
        """Last-resort: scrape a bare timedtext URL out of the page."""
        matches = _PATTERN_TIMEDTEXT.findall(html_content)
        if not matches:
            return {}

        url = matches[0]
        if not url.startswith("http"):
            url = f"https://www.youtube.com{url}"

        return {
            "en": [
                {
                    "language_code": "en",
                    "language": "English",
                    "url": url,
                    "is_generated": True,
                    "is_translatable": False,
                    "translation_languages": [],
                }
            ]
        }
