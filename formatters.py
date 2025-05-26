"""
Formatters for converting transcript data to different output formats.
"""

import json
import html
from typing import List, Dict, Any
from abc import ABC, abstractmethod


class Formatter(ABC):
    """
    Base class for transcript formatters.
    """
    
    @abstractmethod
    def format_transcript(self, transcript: List[Dict], **kwargs) -> str:
        """
        Format transcript data.
        
        Args:
            transcript: List of transcript entries
            **kwargs: Additional formatting options
            
        Returns:
            Formatted transcript string
        """
        pass


class PrettyPrintFormatter(Formatter):
    """
    Formatter for human-readable output.
    """
    
    def format_transcript(self, transcript: List[Dict], **kwargs) -> str:
        """
        Format transcript for pretty printing.
        
        Args:
            transcript: List of transcript entries
            **kwargs: Additional options (show_timestamps, max_chars_per_line)
            
        Returns:
            Pretty formatted transcript string
        """
        show_timestamps = kwargs.get('show_timestamps', True)
        max_chars_per_line = kwargs.get('max_chars_per_line', 80)
        
        formatted_lines = []
        
        for entry in transcript:
            text = entry['text']
            start = entry['start']
            duration = entry['duration']
            
            if show_timestamps:
                timestamp = self._format_timestamp(start)
                line = f"[{timestamp}] {text}"
            else:
                line = text
                
            # Wrap long lines
            if max_chars_per_line and len(line) > max_chars_per_line:
                wrapped_lines = self._wrap_text(line, max_chars_per_line)
                formatted_lines.extend(wrapped_lines)
            else:
                formatted_lines.append(line)
                
        return '\n'.join(formatted_lines)

    def _format_timestamp(self, seconds: float) -> str:
        """
        Format seconds as MM:SS or HH:MM:SS.
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    def _wrap_text(self, text: str, max_chars: int) -> List[str]:
        """
        Wrap text to specified character limit.
        """
        words = text.split()
        lines = []
        current_line = []
        current_length = 0
        
        for word in words:
            word_length = len(word) + 1  # +1 for space
            
            if current_length + word_length > max_chars and current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
                current_length = len(word)
            else:
                current_line.append(word)
                current_length += word_length
                
        if current_line:
            lines.append(' '.join(current_line))
            
        return lines


class JSONFormatter(Formatter):
    """
    Formatter for JSON output.
    """
    
    def format_transcript(self, transcript: List[Dict], **kwargs) -> str:
        """
        Format transcript as JSON.
        
        Args:
            transcript: List of transcript entries
            **kwargs: Additional options (indent, ensure_ascii)
            
        Returns:
            JSON formatted transcript string
        """
        indent = kwargs.get('indent', 2)
        ensure_ascii = kwargs.get('ensure_ascii', False)
        
        return json.dumps(transcript, indent=indent, ensure_ascii=ensure_ascii)


class TextFormatter(Formatter):
    """
    Formatter for plain text output.
    """
    
    def format_transcript(self, transcript: List[Dict], **kwargs) -> str:
        """
        Format transcript as plain text.
        
        Args:
            transcript: List of transcript entries
            **kwargs: Additional options (separator)
            
        Returns:
            Plain text transcript
        """
        separator = kwargs.get('separator', ' ')
        
        text_parts = []
        for entry in transcript:
            text_parts.append(entry['text'])
            
        return separator.join(text_parts)


class SRTFormatter(Formatter):
    """
    Formatter for SRT (SubRip) subtitle format.
    """
    
    def format_transcript(self, transcript: List[Dict], **kwargs) -> str:
        """
        Format transcript as SRT subtitles.
        
        Args:
            transcript: List of transcript entries
            
        Returns:
            SRT formatted transcript
        """
        srt_entries = []
        
        for i, entry in enumerate(transcript, 1):
            start_time = self._format_srt_timestamp(entry['start'])
            end_time = self._format_srt_timestamp(entry['start'] + entry['duration'])
            text = entry['text']
            
            srt_entry = f"{i}\n{start_time} --> {end_time}\n{text}\n"
            srt_entries.append(srt_entry)
            
        return '\n'.join(srt_entries)

    def _format_srt_timestamp(self, seconds: float) -> str:
        """
        Format timestamp for SRT format (HH:MM:SS,mmm).
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


class VTTFormatter(Formatter):
    """
    Formatter for WebVTT subtitle format.
    """
    
    def format_transcript(self, transcript: List[Dict], **kwargs) -> str:
        """
        Format transcript as WebVTT subtitles.
        
        Args:
            transcript: List of transcript entries
            
        Returns:
            WebVTT formatted transcript
        """
        vtt_entries = ["WEBVTT\n"]
        
        for entry in transcript:
            start_time = self._format_vtt_timestamp(entry['start'])
            end_time = self._format_vtt_timestamp(entry['start'] + entry['duration'])
            text = entry['text']
            
            vtt_entry = f"{start_time} --> {end_time}\n{text}\n"
            vtt_entries.append(vtt_entry)
            
        return '\n'.join(vtt_entries)

    def _format_vtt_timestamp(self, seconds: float) -> str:
        """
        Format timestamp for WebVTT format (HH:MM:SS.mmm).
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


# Utility function to get formatter by name
def get_formatter(formatter_name: str) -> Formatter:
    """
    Get formatter instance by name.
    
    Args:
        formatter_name: Name of the formatter ('pretty', 'json', 'text', 'srt', 'vtt')
        
    Returns:
        Formatter instance
        
    Raises:
        ValueError: If formatter name is not recognized
    """
    formatters = {
        'pretty': PrettyPrintFormatter,
        'json': JSONFormatter,
        'text': TextFormatter,
        'srt': SRTFormatter,
        'vtt': VTTFormatter
    }
    
    if formatter_name.lower() not in formatters:
        raise ValueError(f"Unknown formatter: {formatter_name}. Available: {list(formatters.keys())}")
        
    return formatters[formatter_name.lower()]()
