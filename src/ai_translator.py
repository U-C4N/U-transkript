from __future__ import annotations

import json
import requests
from youtube_transcript import YouTubeTranscriptApi
from formatters import get_formatter, JSONFormatter, TextFormatter
from utils.retry import retry
from utils.security import validate_url


class AITranscriptTranslator:
    """
    AI-powered transcript translator using Google Gemini API.
    """
    
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        """
        Initialize the AI translator.

        Args:
            api_key: Google Gemini API key
            model: Gemini model to use (default: gemini-2.5-flash)
        """
        self.api_key = api_key
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        
    def set_model(self, model_name: str) -> AITranscriptTranslator:
        """
        Set the Gemini model to use.
        
        Args:
            model_name: Name of the Gemini model
            
        Returns:
            Self for method chaining
        """
        self.model = model_name
        return self
        
    def set_api(self, api_key: str) -> AITranscriptTranslator:
        """
        Set the API key.
        
        Args:
            api_key: Google Gemini API key
            
        Returns:
            Self for method chaining
        """
        self.api_key = api_key
        return self
        
    def set_lang(self, target_language: str) -> AITranscriptTranslator:
        """
        Set the target language for translation.
        
        Args:
            target_language: Target language (e.g., 'Turkish', 'English', 'Spanish')
            
        Returns:
            Self for method chaining
        """
        self.target_language = target_language
        return self
        
    def set_type(self, output_type: str) -> AITranscriptTranslator:
        """
        Set the output format type.
        
        Args:
            output_type: Output format ('txt', 'json', 'xml')
            
        Returns:
            Self for method chaining
        """
        self.output_type = output_type.lower()
        return self
        
    def translate_transcript(
        self, 
        video_id: str, 
        target_language: str | None = None,
        output_type: str | None = None,
        custom_prompt: str | None = None
    ) -> str:
        """
        Extract and translate YouTube transcript using AI.
        
        Args:
            video_id: YouTube video ID
            target_language: Target language for translation
            output_type: Output format ('txt', 'json', 'xml')
            custom_prompt: Custom prompt for AI translation
            
        Returns:
            Translated transcript in specified format
        """
        # Use instance variables if parameters not provided
        target_lang = target_language or getattr(self, 'target_language', 'English')
        output_fmt = output_type or getattr(self, 'output_type', 'txt')
        
        # Extract transcript
        try:
            raw_transcript_data = YouTubeTranscriptApi.get_transcript(video_id)
            
            # Gelen verinin liste olup olmadığını ve sözlük içerip içermediğini kontrol et
            if not isinstance(raw_transcript_data, list) or \
               not all(isinstance(item, dict) and 'text' in item for item in raw_transcript_data):
                error_message = f"Unexpected transcript data format. Expected List[Dict[str, any]], got: {type(raw_transcript_data)}"
                if isinstance(raw_transcript_data, list) and raw_transcript_data:
                    error_message += f" First item type: {type(raw_transcript_data[0])}"
                raise Exception(error_message)
            transcript = raw_transcript_data
        except Exception as e:
            # Hata mesajına video_id'yi ekleyerek daha anlaşılır hale getirelim
            raise Exception(f"Failed to extract or validate transcript for video_id '{video_id}': {str(e)}")
            
        # Combine transcript text
        full_text = " ".join([entry['text'] for entry in transcript])
        
        # Translate using Gemini AI
        translated_text = self._translate_with_gemini(
            full_text, 
            target_lang, 
            custom_prompt
        )
        
        # Format output
        return self._format_output(translated_text, transcript, output_fmt)
        
    @retry(
        max_attempts=3,
        backoff_factor=1.5,
        jitter=True,
        exceptions=(requests.exceptions.RequestException,),
    )
    def _call_gemini_api(self, url: str, headers: dict, data: dict):
        """Make a request to the Gemini API with retry for transient errors."""
        validate_url(url)
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response

    def _translate_with_gemini(
        self,
        text: str,
        target_language: str,
        custom_prompt: str | None = None
    ) -> str:
        """
        Translate text using Google Gemini API.

        Args:
            text: Text to translate
            target_language: Target language
            custom_prompt: Custom prompt for translation

        Returns:
            Translated text
        """
        if custom_prompt:
            prompt = custom_prompt.format(text=text, language=target_language)
        else:
            prompt = f"""
            Please translate the following text to {target_language}.
            Maintain the natural flow and context of the content.
            Only return the translated text without any additional comments or explanations.

            Text to translate:
            {text}
            """

        url = f"{self.base_url}/{self.model}:generateContent"

        headers = {
            'Content-Type': 'application/json',
            'x-goog-api-key': self.api_key,
        }

        data = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }]
        }

        try:
            response = self._call_gemini_api(url, headers, data)
            result = response.json()

            if 'candidates' in result and len(result['candidates']) > 0:
                if 'content' in result['candidates'][0]:
                    if 'parts' in result['candidates'][0]['content']:
                        return result['candidates'][0]['content']['parts'][0]['text'].strip()

            raise Exception("Invalid response format from Gemini API")

        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")
        except Exception as e:
            raise Exception(f"Translation failed: {str(e)}")
            
    def _format_output(
        self, 
        translated_text: str, 
        original_transcript: list[dict],
        output_type: str
    ) -> str:
        """
        Format the translated text according to specified output type.
        
        Args:
            translated_text: Translated text
            original_transcript: Original transcript with timestamps
            output_type: Output format type
            
        Returns:
            Formatted output
        """
        if output_type == 'txt':
            return translated_text
            
        elif output_type == 'json':
            # Create a structured JSON with translation
            result = {
                "video_id": getattr(self, '_current_video_id', 'unknown'),
                "target_language": getattr(self, 'target_language', 'unknown'),
                "original_transcript": original_transcript,
                "translated_text": translated_text,
                "translation_metadata": {
                    "model": self.model,
                    "timestamp": self._get_current_timestamp()
                }
            }
            return json.dumps(result, indent=2, ensure_ascii=False)
            
        elif output_type == 'xml':
            # Use list append + join instead of string concatenation
            parts = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<transcript>',
                '    <metadata>',
                f'        <video_id>{getattr(self, "_current_video_id", "unknown")}</video_id>',
                f'        <target_language>{getattr(self, "target_language", "unknown")}</target_language>',
                f'        <model>{self.model}</model>',
                f'        <timestamp>{self._get_current_timestamp()}</timestamp>',
                '    </metadata>',
                '    <original_transcript>',
            ]
            for entry in original_transcript:
                parts.append(f'        <entry start="{entry["start"]}" duration="{entry["duration"]}">')
                parts.append(f'            <text>{self._escape_xml(entry["text"])}</text>')
                parts.append('        </entry>')
            parts.append('    </original_transcript>')
            parts.append('    <translated_text>')
            parts.append(f'        <![CDATA[{translated_text}]]>')
            parts.append('    </translated_text>')
            parts.append('</transcript>')
            return '\n'.join(parts)
            
        else:
            raise ValueError(f"Unsupported output type: {output_type}")
            
    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import datetime
        return datetime.now().isoformat()
        
    def _escape_xml(self, text: str) -> str:
        """Escape XML special characters."""
        return (text.replace('&', '&amp;')
                   .replace('<', '&lt;')
                   .replace('>', '&gt;')
                   .replace('"', '&quot;')
                   .replace("'", '&#39;'))
 