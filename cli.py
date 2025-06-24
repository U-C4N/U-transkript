import argparse
import sys
import json
import os
from typing import List, Optional

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from youtube_transcript import YouTubeTranscriptApi
from formatters import get_formatter
from exceptions import TranscriptRetrievalError


def extract_video_id(url_or_id: str) -> str:
    """
    Extract video ID from YouTube URL or return ID if already extracted.
    
    Args:
        url_or_id: YouTube URL or video ID
        
    Returns:
        Video ID
    """
    # Common YouTube URL patterns
    import re
    
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'  # Direct video ID
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
            
    raise ValueError(f"Could not extract video ID from: {url_or_id}")


def main():
    """
    Main CLI function.
    """
    parser = argparse.ArgumentParser(
        description='Extract transcripts from YouTube videos',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s dQw4w9WgXcQ
  %(prog)s "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  %(prog)s dQw4w9WgXcQ --languages en es fr
  %(prog)s dQw4w9WgXcQ --format json
  %(prog)s dQw4w9WgXcQ --format srt --output transcript.srt
  %(prog)s dQw4w9WgXcQ --list-transcripts
        """
    )
    
    parser.add_argument(
        'video',
        help='YouTube video URL or video ID'
    )
    
    parser.add_argument(
        '--languages', '-l',
        nargs='+',
        help='Language codes in order of preference (e.g., en es fr)'
    )
    
    parser.add_argument(
        '--format', '-f',
        choices=['pretty', 'json', 'text', 'srt', 'vtt'],
        default='pretty',
        help='Output format (default: pretty)'
    )
    
    parser.add_argument(
        '--output', '-o',
        help='Output file (default: stdout)'
    )
    
    parser.add_argument(
        '--list-transcripts',
        action='store_true',
        help='List available transcripts for the video'
    )
    
    parser.add_argument(
        '--generated-only',
        action='store_true',
        help='Only use auto-generated transcripts'
    )
    
    parser.add_argument(
        '--manual-only',
        action='store_true',
        help='Only use manually created transcripts'
    )
    
    parser.add_argument(
        '--preserve-formatting',
        action='store_true',
        help='Preserve HTML formatting in transcript text'
    )
    
    parser.add_argument(
        '--proxy',
        help='Proxy URL (e.g., http://proxy:8080)'
    )
    
    parser.add_argument(
        '--cookies',
        help='Cookie string for authentication'
    )
    
    parser.add_argument(
        '--exclude-generated',
        action='store_true',
        help='Exclude auto-generated transcripts'
    )
    
    parser.add_argument(
        '--exclude-manual',
        action='store_true',
        help='Exclude manually created transcripts'
    )
    
    args = parser.parse_args()
    
    try:
        # Extract video ID
        video_id = extract_video_id(args.video)
        
        # Setup proxy configuration
        proxies = None
        if args.proxy:
            proxies = {
                'http': args.proxy,
                'https': args.proxy
            }
            
        # List transcripts if requested
        if args.list_transcripts:
            transcript_list = YouTubeTranscriptApi.list_transcripts(
                video_id,
                proxies=proxies,
                cookies=args.cookies
            )
            
            print(f"Available transcripts for video {video_id}:")
            print("-" * 50)
            
            for transcript in transcript_list:
                status_flags = []
                if transcript.is_generated:
                    status_flags.append("AUTO-GENERATED")
                else:
                    status_flags.append("MANUAL")
                    
                if transcript.is_translatable:
                    status_flags.append("TRANSLATABLE")
                    
                status_str = " [" + ", ".join(status_flags) + "]"
                print(f"  {transcript.language_code}: {transcript.language}{status_str}")
                
                if transcript.is_translatable and transcript.translation_languages:
                    print(f"    Translation languages: {len(transcript.translation_languages)} available")
                    
            return
            
        # Get transcript
        if args.generated_only and args.manual_only:
            print("Error: Cannot specify both --generated-only and --manual-only", file=sys.stderr)
            sys.exit(1)
            
        if args.exclude_generated and args.exclude_manual:
            print("Error: Cannot exclude both generated and manual transcripts", file=sys.stderr)
            sys.exit(1)
            
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=args.languages,
            proxies=proxies,
            cookies=args.cookies,
            preserve_formatting=args.preserve_formatting
        )
        
        # Filter transcript based on type preferences
        if args.generated_only or args.manual_only or args.exclude_generated or args.exclude_manual:
            transcript_list = YouTubeTranscriptApi.list_transcripts(
                video_id,
                proxies=proxies,
                cookies=args.cookies
            )
            
            if args.generated_only:
                transcript_obj = transcript_list.find_generated_transcript(args.languages or ['en'])
            elif args.manual_only:
                transcript_obj = transcript_list.find_manually_created_transcript(args.languages or ['en'])
            else:
                # Use exclude filters
                available_transcripts = list(transcript_list)
                if args.exclude_generated:
                    available_transcripts = [t for t in available_transcripts if not t.is_generated]
                if args.exclude_manual:
                    available_transcripts = [t for t in available_transcripts if t.is_generated]
                    
                if not available_transcripts:
                    print("Error: No transcripts available after applying filters", file=sys.stderr)
                    sys.exit(1)
                    
                transcript_obj = available_transcripts[0]
                
            transcript = transcript_obj.fetch(preserve_formatting=args.preserve_formatting)
        
        # Format transcript
        formatter = get_formatter(args.format)
        
        # Prepare formatter options
        formatter_kwargs = {}
        if args.format == 'pretty':
            formatter_kwargs['show_timestamps'] = True
            formatter_kwargs['max_chars_per_line'] = 80
        elif args.format == 'json':
            formatter_kwargs['indent'] = 2
            formatter_kwargs['ensure_ascii'] = False
        elif args.format == 'text':
            formatter_kwargs['separator'] = ' '
            
        formatted_transcript = formatter.format_transcript(transcript, **formatter_kwargs)
        
        # Output transcript
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(formatted_transcript)
            print(f"Transcript saved to {args.output}")
        else:
            print(formatted_transcript)
            
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(1)
    except TranscriptRetrievalError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
