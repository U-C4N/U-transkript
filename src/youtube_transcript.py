import json
import re
import requests
import time
import urllib.parse
from typing import List, Dict, Optional, Union
from xml.etree import ElementTree

from exceptions import (
    TranscriptRetrievalError,
    VideoUnavailable,
    TranscriptNotFound,
    TranscriptDisabled,
    NoTranscriptFound,
    TooManyRequests,
    CookiesInvalid,
    NotTranslatable,
    TranslationLanguageNotAvailable
)
from transcript_list import TranscriptList
from fetched_transcript import FetchedTranscript


class YouTubeTranscriptApi:
    """
    Main class for retrieving YouTube video transcripts.
    """
    
    _WATCH_URL = 'https://www.youtube.com/watch?v={video_id}'
    _API_BASE_URL = 'https://www.youtube.com/api/timedtext'
    
    @classmethod
    def get_transcript(
        cls,
        video_id: str,
        languages: List[str] = None,
        proxies: Dict = None,
        cookies: str = None,
        preserve_formatting: bool = False
    ) -> List[Dict]:
        """
        Retrieve transcript for a single video.
        
        Args:
            video_id: YouTube video ID
            languages: List of language codes in order of preference
            proxies: Proxy configuration for requests
            cookies: Cookie string for authentication
            preserve_formatting: Whether to preserve HTML formatting
            
        Returns:
            List of transcript entries with 'text', 'start', and 'duration' keys
        """
        transcript_list = cls.list_transcripts(video_id, proxies=proxies, cookies=cookies)
        
        if languages:
            for language_code in languages:
                try:
                    transcript = transcript_list.find_transcript([language_code])
                    return transcript.fetch(preserve_formatting=preserve_formatting)
                except (NoTranscriptFound, TranscriptNotFound):
                    continue
            
            # If no exact match found, try to get a translatable transcript
            try:
                transcript = transcript_list.find_manually_created_transcript(languages)
                if transcript.is_translatable:
                    if languages:
                        target_lang_code_for_translation = languages[0]
                        try:
                            translated = transcript.translate(target_lang_code_for_translation)
                            return translated.fetch(preserve_formatting=preserve_formatting)
                        except Exception:
                            pass
            except (NoTranscriptFound, TranscriptNotFound):
                pass
                
            raise NoTranscriptFound(video_id, languages, transcript_list._transcript_data if hasattr(transcript_list, '_transcript_data') else {})
        else:
            # No specific languages requested, try common fallbacks
            try:
                # Attempt to find an English generated transcript
                transcript = transcript_list.find_generated_transcript(['en'])
                return transcript.fetch(preserve_formatting=preserve_formatting)
            except NoTranscriptFound: 
                try:
                    # Attempt to find an English manually created transcript
                    transcript = transcript_list.find_manually_created_transcript(['en'])
                    return transcript.fetch(preserve_formatting=preserve_formatting)
                except NoTranscriptFound: 
                    # Fallback to the very first transcript available in the list
                    if transcript_list._transcript_data:
                        first_transcript_info_dict = None
                        for lang_key in transcript_list._transcript_data: 
                            if transcript_list._transcript_data[lang_key]: 
                                first_transcript_info_dict = transcript_list._transcript_data[lang_key][0]
                                break 

                        if first_transcript_info_dict:
                            actual_transcript_object = FetchedTranscript(
                                video_id=video_id,
                                language_code=first_transcript_info_dict['language_code'],
                                language=first_transcript_info_dict['language'],
                                url=first_transcript_info_dict['url'],
                                is_generated=first_transcript_info_dict['is_generated'],
                                is_translatable=first_transcript_info_dict['is_translatable'],
                                translation_languages=first_transcript_info_dict.get('translation_languages', []),
                                proxies=proxies,
                                cookies=cookies
                            )
                            return actual_transcript_object.fetch(preserve_formatting=preserve_formatting)
                    # If after all this, no transcript is found
                    raise TranscriptNotFound(video_id)

    @classmethod
    def get_transcripts(
        cls,
        video_ids: List[str],
        languages: List[str] = None,
        proxies: Dict = None,
        cookies: str = None,
        preserve_formatting: bool = False,
        continue_on_failure: bool = False
    ) -> List[Dict]:
        """
        Retrieve transcripts for multiple videos.
        
        Args:
            video_ids: List of YouTube video IDs
            languages: List of language codes in order of preference
            proxies: Proxy configuration for requests
            cookies: Cookie string for authentication
            preserve_formatting: Whether to preserve HTML formatting
            continue_on_failure: Whether to continue if a video fails
            
        Returns:
            List of dictionaries with video_id and transcript data
        """
        results = []
        
        for video_id in video_ids:
            try:
                transcript = cls.get_transcript(
                    video_id,
                    languages=languages,
                    proxies=proxies,
                    cookies=cookies,
                    preserve_formatting=preserve_formatting
                )
                results.append({
                    'video_id': video_id,
                    'transcript': transcript,
                    'error': None
                })
            except Exception as e:
                if continue_on_failure:
                    results.append({
                        'video_id': video_id,
                        'transcript': None,
                        'error': str(e)
                    })
                else:
                    raise e
                    
        return results

    @classmethod
    def list_transcripts(
        cls,
        video_id: str,
        proxies: Dict = None,
        cookies: str = None,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> TranscriptList:
        """
        List all available transcripts for a video.

        Args:
            video_id: YouTube video ID
            proxies: Proxy configuration for requests
            cookies: Cookie string for authentication
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds

        Returns:
            TranscriptList object containing all available transcripts
        """
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                # First, get the video page to extract transcript data
                watch_url = cls._WATCH_URL.format(video_id=video_id)

                session = requests.Session()
                if proxies:
                    session.proxies.update(proxies)

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }

                if cookies:
                    headers['Cookie'] = cookies

                response = session.get(watch_url, headers=headers, timeout=30)

                if response.status_code == 429:
                    if attempt < max_retries:
                        time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                        continue
                    raise TooManyRequests(video_id)
                elif response.status_code == 404:
                    raise VideoUnavailable(video_id)
                elif response.status_code != 200:
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        continue
                    raise VideoUnavailable(video_id)

                # Extract transcript data from the page
                transcript_data = cls._extract_transcript_data(response.text, video_id)

                if not transcript_data:
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        continue
                    raise TranscriptNotFound(video_id)

                return TranscriptList(video_id, transcript_data, proxies=proxies, cookies=cookies)

            except (TranscriptRetrievalError, TooManyRequests, VideoUnavailable, TranscriptNotFound):
                raise
            except requests.exceptions.Timeout as e:
                last_exception = TranscriptRetrievalError(video_id, f"Request timeout: {str(e)}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
            except requests.exceptions.ConnectionError as e:
                last_exception = TranscriptRetrievalError(video_id, f"Connection error: {str(e)}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
            except Exception as e:
                last_exception = TranscriptRetrievalError(video_id, f"Failed to retrieve transcript list: {str(e)}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue

        # If all retries failed, raise the last exception
        raise last_exception or TranscriptRetrievalError(video_id, "Failed to retrieve transcript list after all retries")

    @classmethod
    def _extract_transcript_data(cls, html_content: str, video_id: str) -> Dict:
        """
        Extract transcript data from YouTube video page HTML.

        Args:
            html_content: HTML content of the video page
            video_id: YouTube video ID

        Returns:
            Dictionary containing transcript data
        """
        # First, try to use Innertube API
        try:
            api_key = cls._extract_innertube_api_key(html_content)
            if api_key:
                innertube_data = cls._fetch_innertube_data(video_id, api_key)
                if innertube_data:
                    captions_data = cls._extract_captions_from_innertube(innertube_data)
                    if captions_data:
                        return cls._parse_transcript_data(captions_data, video_id)
        except Exception:
            pass  # Fallback to HTML parsing

        # Fallback: Look for captions data in the HTML with improved patterns
        patterns = [
            # Modern YouTube patterns
            r'"captions":\s*\{[^}]*"playerCaptionsTracklistRenderer":\s*(\{.*?\})',
            r'"playerCaptionsTracklistRenderer":\s*(\{.*?"captionTracks".*?\})',
            r'ytInitialPlayerResponse["\']?:\s*(\{.*?\})',
            r'var\s+ytInitialPlayerResponse\s*=\s*(\{.*?\});',
            # Alternative patterns for different YouTube layouts
            r'"captionTracks":\s*\[(.*?)\]',
            r'"playerCaptionsRenderer":\s*(\{.*?\})',
            # Backup patterns
            r'"captions":(\{.*?"playerCaptionsTracklistRenderer".*?\})',
            r'ytInitialPlayerResponse":\s*(\{.*?\})\s*[,}]'
        ]

        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                try:
                    data = json.loads(match.group(1))
                    captions_data = cls._find_captions_data(data)
                    if captions_data:
                        return cls._parse_transcript_data(captions_data, video_id)
                except (json.JSONDecodeError, KeyError):
                    continue

        # If no captions found in initial data, try alternative extraction
        return cls._extract_alternative_transcript_data(html_content, video_id)

    @classmethod
    def _find_captions_data(cls, data: Dict) -> Optional[Dict]:
        """
        Recursively find captions data in nested dictionary.
        """
        if isinstance(data, dict):
            if 'playerCaptionsTracklistRenderer' in data:
                return data['playerCaptionsTracklistRenderer']
            
            for key, value in data.items():
                if key == 'captions' and isinstance(value, dict):
                    if 'playerCaptionsTracklistRenderer' in value:
                        return value['playerCaptionsTracklistRenderer']
                
                result = cls._find_captions_data(value)
                if result:
                    return result
                    
        elif isinstance(data, list):
            for item in data:
                result = cls._find_captions_data(item)
                if result:
                    return result
                    
        return None

    @classmethod
    def _parse_transcript_data(cls, captions_data: Dict, video_id: str) -> Dict:
        """
        Parse captions data into transcript format.
        """
        transcript_data = {}
        
        caption_tracks = captions_data.get('captionTracks', [])
        translation_languages = captions_data.get('translationLanguages', [])
        
        for track in caption_tracks:
            language_code = track.get('languageCode', 'unknown')
            base_url = track.get('baseUrl', '')
            
            if not base_url:
                continue
                
            # Determine if this is auto-generated
            is_auto = track.get('kind') == 'asr'
            
            transcript_info = {
                'language_code': language_code,
                'language': track.get('name', {}).get('simpleText', language_code),
                'url': base_url,
                'is_generated': is_auto,
                'is_translatable': bool(translation_languages),
                'translation_languages': []
            }
            
            # Add translation languages if available
            if translation_languages:
                for lang in translation_languages:
                    transcript_info['translation_languages'].append({
                        'language_code': lang.get('languageCode', ''),
                        'language': lang.get('languageName', {}).get('simpleText', '')
                    })
            
            if language_code not in transcript_data:
                transcript_data[language_code] = []
            transcript_data[language_code].append(transcript_info)
            
        return transcript_data

    @classmethod
    def _extract_innertube_api_key(cls, html_content: str) -> Optional[str]:
        """
        Extract Innertube API key from YouTube page HTML.

        Args:
            html_content: HTML content of the video page

        Returns:
            API key string or None if not found
        """
        patterns = [
            r'"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"',
            r'"innertubeApiKey":\s*"([a-zA-Z0-9_-]+)"',
            r'"apiKey":\s*"([a-zA-Z0-9_-]+)"'
        ]

        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                return match.group(1)

        return None

    @classmethod
    def _fetch_innertube_data(cls, video_id: str, api_key: str) -> Optional[Dict]:
        """
        Fetch transcript data from YouTube Innertube API.

        Args:
            video_id: YouTube video ID
            api_key: Innertube API key

        Returns:
            Innertube response data or None if failed
        """
        url = f"https://www.youtube.com/youtubei/v1/player?key={api_key}"

        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

        data = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20231201.01.00"
                }
            },
            "videoId": video_id
        }

        try:
            response = requests.post(url, headers=headers, json=data)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass

        return None

    @classmethod
    def _extract_captions_from_innertube(cls, innertube_data: Dict) -> Optional[Dict]:
        """
        Extract captions data from Innertube API response.

        Args:
            innertube_data: Response from Innertube API

        Returns:
            Captions data or None if not found
        """
        try:
            captions = innertube_data.get('captions', {})
            if 'playerCaptionsTracklistRenderer' in captions:
                return captions['playerCaptionsTracklistRenderer']
        except Exception:
            pass

        return None

    @classmethod
    def _extract_alternative_transcript_data(cls, html_content: str, video_id: str) -> Dict:
        """
        Alternative method to extract transcript data if primary method fails.
        """
        # Look for any mention of timedtext or captions
        timedtext_pattern = r'["\']timedtext["\'].*?["\']([^"\']*)["\']'
        matches = re.findall(timedtext_pattern, html_content, re.IGNORECASE)

        if matches:
            # This is a simplified fallback - in a real implementation,
            # you might need more sophisticated parsing
            return {
                'en': [{
                    'language_code': 'en',
                    'language': 'English',
                    'url': matches[0] if matches[0].startswith('http') else f"https://www.youtube.com{matches[0]}",
                    'is_generated': True,
                    'is_translatable': False,
                    'translation_languages': []
                }]
            }

        return {}
