from typing import List, Dict, Optional, Union
from fetched_transcript import FetchedTranscript
from exceptions import (
    NoTranscriptFound,
    TranscriptNotFound,
    NotTranslatable,
    TranslationLanguageNotAvailable
)


class TranscriptList:
    """
    Represents a list of available transcripts for a YouTube video.
    """
    
    def __init__(self, video_id: str, transcript_data: Dict, proxies: Dict = None, cookies: str = None):
        """
        Initialize TranscriptList.
        
        Args:
            video_id: YouTube video ID
            transcript_data: Dictionary containing transcript information
            proxies: Proxy configuration for requests
            cookies: Cookie string for authentication
        """
        self.video_id = video_id
        self._transcript_data = transcript_data
        self._proxies = proxies
        self._cookies = cookies
        
        # Build transcript objects
        self._transcripts = {}
        self._generated_transcripts = {}
        self._manually_created_transcripts = {}
        
        for language_code, transcripts in transcript_data.items():
            for transcript_info in transcripts:
                transcript = FetchedTranscript(
                    video_id=video_id,
                    language_code=language_code,
                    language=transcript_info['language'],
                    url=transcript_info['url'],
                    is_generated=transcript_info['is_generated'],
                    is_translatable=transcript_info['is_translatable'],
                    translation_languages=transcript_info['translation_languages'],
                    proxies=proxies,
                    cookies=cookies
                )
                
                self._transcripts[language_code] = transcript
                
                if transcript_info['is_generated']:
                    self._generated_transcripts[language_code] = transcript
                else:
                    self._manually_created_transcripts[language_code] = transcript

    def __iter__(self):
        """
        Iterate over all available transcripts.
        """
        return iter(self._transcripts.values())

    def __len__(self):
        """
        Return the number of available transcripts.
        """
        return len(self._transcripts)

    def find_transcript(self, language_codes: List[str]) -> FetchedTranscript:
        """
        Find a transcript for one of the given language codes.
        
        Args:
            language_codes: List of language codes in order of preference
            
        Returns:
            FetchedTranscript object
            
        Raises:
            NoTranscriptFound: If no transcript is found for any of the languages
        """
        for language_code in language_codes:
            if language_code in self._transcripts:
                return self._transcripts[language_code]
                
        # Try to find a translatable transcript
        for language_code in language_codes:
            for transcript in self._transcripts.values():
                if transcript.is_translatable:
                    try:
                        return transcript.translate(language_code)
                    except (NotTranslatable, TranslationLanguageNotAvailable):
                        continue
                        
        raise NoTranscriptFound(self.video_id, language_codes, self._transcript_data)

    def find_generated_transcript(self, language_codes: List[str]) -> FetchedTranscript:
        """
        Find an automatically generated transcript.
        
        Args:
            language_codes: List of language codes in order of preference
            
        Returns:
            FetchedTranscript object for auto-generated transcript
            
        Raises:
            NoTranscriptFound: If no auto-generated transcript is found
        """
        for language_code in language_codes:
            if language_code in self._generated_transcripts:
                return self._generated_transcripts[language_code]
                
        # Try to find a translatable auto-generated transcript
        for language_code in language_codes:
            for transcript in self._generated_transcripts.values():
                if transcript.is_translatable:
                    try:
                        return transcript.translate(language_code)
                    except (NotTranslatable, TranslationLanguageNotAvailable):
                        continue
                        
        raise NoTranscriptFound(self.video_id, language_codes, self._transcript_data)

    def find_manually_created_transcript(self, language_codes: List[str]) -> FetchedTranscript:
        """
        Find a manually created transcript.
        
        Args:
            language_codes: List of language codes in order of preference
            
        Returns:
            FetchedTranscript object for manually created transcript
            
        Raises:
            NoTranscriptFound: If no manually created transcript is found
        """
        for language_code in language_codes:
            if language_code in self._manually_created_transcripts:
                return self._manually_created_transcripts[language_code]
                
        # Try to find a translatable manually created transcript
        for language_code in language_codes:
            for transcript in self._manually_created_transcripts.values():
                if transcript.is_translatable:
                    try:
                        return transcript.translate(language_code)
                    except (NotTranslatable, TranslationLanguageNotAvailable):
                        continue
                        
        raise NoTranscriptFound(self.video_id, language_codes, self._transcript_data)

    def get_languages(self) -> List[str]:
        """
        Get list of all available language codes.
        
        Returns:
            List of language codes
        """
        return list(self._transcripts.keys())

    def get_generated_languages(self) -> List[str]:
        """
        Get list of language codes for auto-generated transcripts.
        
        Returns:
            List of language codes for auto-generated transcripts
        """
        return list(self._generated_transcripts.keys())

    def get_manually_created_languages(self) -> List[str]:
        """
        Get list of language codes for manually created transcripts.
        
        Returns:
            List of language codes for manually created transcripts
        """
        return list(self._manually_created_transcripts.keys())

    def is_translatable(self, language_code: str) -> bool:
        """
        Check if a transcript is translatable.
        
        Args:
            language_code: Language code to check
            
        Returns:
            True if transcript is translatable, False otherwise
        """
        if language_code in self._transcripts:
            return self._transcripts[language_code].is_translatable
        return False

    def get_translation_languages(self, language_code: str) -> List[Dict[str, str]]:
        """
        Get available translation languages for a transcript.
        
        Args:
            language_code: Source language code
            
        Returns:
            List of dictionaries with language_code and language name
        """
        if language_code in self._transcripts:
            return self._transcripts[language_code].translation_languages
        return []

    def __repr__(self):
        """
        String representation of TranscriptList.
        """
        transcript_info = []
        for transcript in self._transcripts.values():
            info = f"{transcript.language_code} ({transcript.language})"
            if transcript.is_generated:
                info += " [GENERATED]"
            if transcript.is_translatable:
                info += " [TRANSLATABLE]"
            transcript_info.append(info)
            
        return f"TranscriptList(video_id='{self.video_id}', transcripts=[{', '.join(transcript_info)}])"
