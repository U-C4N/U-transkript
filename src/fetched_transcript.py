import re
import html
import json
import requests
import urllib.parse
from typing import List, Dict, Optional
from xml.etree import ElementTree

from exceptions import (
    TranscriptRetrievalError,
    NotTranslatable,
    TranslationLanguageNotAvailable,
    TooManyRequests
)


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
        translation_languages: List[Dict[str, str]],
        proxies: Dict = None,
        cookies: str = None
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

    def fetch(self, preserve_formatting: bool = False) -> List[Dict]:
        """
        Fetch the transcript data.
        
        Args:
            preserve_formatting: Whether to preserve HTML formatting in text
            
        Returns:
            List of transcript entries with 'text', 'start', and 'duration' keys
        """
        if self._fetched_data is not None:
            return self._process_transcript_data(self._fetched_data, preserve_formatting)
            
        try:
            session = requests.Session()
            if self._proxies:
                session.proxies.update(self._proxies)
                
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            if self._cookies:
                headers['Cookie'] = self._cookies
                
            response = session.get(self.url, headers=headers)
            
            if response.status_code == 429:
                raise TooManyRequests(self.video_id)
            elif response.status_code != 200:
                raise TranscriptRetrievalError(
                    self.video_id,
                    f"Failed to fetch transcript: HTTP {response.status_code}"
                )
                
            self._fetched_data = response.text
            return self._process_transcript_data(self._fetched_data, preserve_formatting)
            
        except TooManyRequests:
            raise
        except Exception as e:
            raise TranscriptRetrievalError(
                self.video_id,
                f"Failed to fetch transcript for language {self.language_code}: {str(e)}"
            )

    def _process_transcript_data(self, xml_data: str, preserve_formatting: bool = False) -> List[Dict]:
        """
        Process XML transcript data into structured format.
        
        Args:
            xml_data: Raw XML transcript data
            preserve_formatting: Whether to preserve HTML formatting
            
        Returns:
            List of transcript entries
        """
        if not xml_data or not xml_data.strip():
            # Gelen veri boşsa, boş liste döndür veya uygun bir hata fırlat.
            # Bu durumda, genellikle bu video için bir transkript olmadığı anlamına gelir.
            # Loglama eklenebilir: print(f"Warning: Empty transcript data received for video {self.video_id}, lang {self.language_code}")
            return [] # Boş transkript olarak kabul et

        try:
            # Parse XML data
            root = ElementTree.fromstring(xml_data)
            transcript_entries = []
            
            for text_element in root.findall('.//text'):
                # Extract timing information
                start = float(text_element.get('start', 0))
                duration = float(text_element.get('dur', 0))
                
                # Extract text content
                text_content = text_element.text or ''
                
                # Process text formatting
                if not preserve_formatting:
                    # Remove HTML tags and decode HTML entities
                    text_content = re.sub(r'<[^>]+>', '', text_content)
                    text_content = html.unescape(text_content)
                
                # Clean up whitespace
                text_content = text_content.strip()
                
                if text_content:  # Only include non-empty entries
                    transcript_entries.append({
                        'text': text_content,
                        'start': start,
                        'duration': duration
                    })
                    
            return transcript_entries
            
        except ElementTree.ParseError as e_xml:
            # If XML parsing fails, try to handle as JSON (some formats)
            try:
                data = json.loads(xml_data)
                return self._process_json_transcript_data(data, preserve_formatting)
            except json.JSONDecodeError as e_json:
                # Hem XML hem de JSON parse edilemezse, bu durumu logla ve boş liste döndür
                # veya daha spesifik bir hata fırlat.
                # print(f"Warning: Could not parse transcript data as XML or JSON for video {self.video_id}, lang {self.language_code}. XML Error: {e_xml}, JSON Error: {e_json}. Data: {xml_data[:200]}...")
                # Hata fırlatmak yerine boş liste döndürmek, AI çevirmeninin boş metinle başa çıkmasını sağlar.
                # raise TranscriptRetrievalError(
                #     self.video_id,
                #     f"Failed to parse transcript data as XML or JSON. XML: {e_xml}, JSON: {e_json}"
                # )
                return [] # Parse edilemeyen veriyi boş transkript olarak kabul et
            except Exception as e_general_json: # json.loads bilinmeyen bir hata verirse
                # print(f"Warning: General error parsing transcript data as JSON for video {self.video_id}, lang {self.language_code}. Error: {e_general_json}. Data: {xml_data[:200]}...")
                return []
        except Exception as e_general_xml: # ElementTree.fromstring bilinmeyen bir hata verirse
            # print(f"Warning: General error parsing transcript data as XML for video {self.video_id}, lang {self.language_code}. Error: {e_general_xml}. Data: {xml_data[:200]}...")
            return []

    def _process_json_transcript_data(self, json_data: Dict, preserve_formatting: bool = False) -> List[Dict]:
        """
        Process JSON transcript data (alternative format).
        """
        transcript_entries = []
        
        # Handle different JSON structures that YouTube might use
        events = json_data.get('events', [])
        
        for event in events:
            if 'segs' in event:
                start_time = event.get('tStartMs', 0) / 1000.0
                text_segments = event['segs']
                
                combined_text = ''
                for segment in text_segments:
                    if 'utf8' in segment:
                        combined_text += segment['utf8']
                
                if combined_text.strip():
                    if not preserve_formatting:
                        combined_text = re.sub(r'<[^>]+>', '', combined_text)
                        combined_text = html.unescape(combined_text)
                    
                    transcript_entries.append({
                        'text': combined_text.strip(),
                        'start': start_time,
                        'duration': event.get('dDurationMs', 0) / 1000.0
                    })
                    
        return transcript_entries

    def translate(self, target_language_code: str) -> 'FetchedTranscript':
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
            
        # Check if target language is available
        available_languages = [lang['language_code'] for lang in self.translation_languages]
        if target_language_code not in available_languages:
            raise TranslationLanguageNotAvailable(
                self.video_id,
                target_language_code,
                available_languages
            )
            
        # Find target language info
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
            
        # Create translated URL
        translated_url = self._create_translated_url(target_language_code)
        
        return FetchedTranscript(
            video_id=self.video_id,
            language_code=target_language_code,
            language=target_language_info['language'],
            url=translated_url,
            is_generated=True,  # Translations are always generated
            is_translatable=False,  # Translations cannot be further translated
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
        # Parse the current URL and add translation parameters
        parsed_url = urllib.parse.urlparse(self.url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        
        # Add translation language parameter
        query_params['tlang'] = [target_language_code]
        
        # Rebuild URL
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
