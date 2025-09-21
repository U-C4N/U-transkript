import argparse
import sys
import json
import os
import re
import requests
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


def build_youtube_channel_url(username: str) -> str:
    """
    Build YouTube channel URL from username.

    Args:
        username: YouTube username (with or without @)

    Returns:
        YouTube channel URL
    """
    # Clean username
    username = username.strip()

    # If it's already a full URL, return as is
    if username.startswith('http'):
        return username

    # If it starts with UC (channel ID), use channel format
    if username.startswith('UC') and len(username) == 24:
        return f"https://www.youtube.com/channel/{username}/videos?sort=dd"

    # Remove @ if present
    if username.startswith('@'):
        username = username[1:]

    # Use handle format (newer format) with sort parameter to get latest videos
    return f"https://www.youtube.com/@{username}/videos?sort=dd"


def get_channel_video_ids(username: str, max_count: int = 10) -> List[str]:
    """
    Get video IDs from a YouTube channel using multiple page requests.

    Args:
        username: YouTube username (with or without @)
        max_count: Maximum number of video IDs to return

    Returns:
        List of video IDs

    Raises:
        RuntimeError: If channel extraction fails
        ValueError: If no videos found
    """
    channel_url = build_youtube_channel_url(username)

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        all_video_ids = []

        # Try both videos and uploads URL formats with sort parameter for latest videos
        urls_to_try = [
            channel_url,
            channel_url.replace('/videos?sort=dd', '/uploads?sort=dd'),
            channel_url.replace('/videos?sort=dd', '?sort=dd'),
            channel_url.replace('@', 'c/'),
            channel_url.replace('@', 'channel/').replace('/videos?sort=dd', '/videos?sort=dd'),
        ]

        for url in urls_to_try:
            try:
                response = requests.get(url, headers=headers)
                response.raise_for_status()

                # Extract video IDs from HTML using multiple regex patterns
                video_id_patterns = [
                    r'"videoId":"([a-zA-Z0-9_-]{11})"',
                    r'/watch\?v=([a-zA-Z0-9_-]{11})',
                    r'"watchEndpoint":{"videoId":"([a-zA-Z0-9_-]{11})"',
                    r'watch\?v=([a-zA-Z0-9_-]{11})',
                    r'"url":"/watch\?v=([a-zA-Z0-9_-]{11})"',
                    r'href="/watch\?v=([a-zA-Z0-9_-]{11})"'
                ]

                for pattern in video_id_patterns:
                    matches = re.findall(pattern, response.text)
                    all_video_ids.extend(matches)

            except:
                continue

        # Remove duplicates while preserving order
        seen = set()
        unique_video_ids = []
        for video_id in all_video_ids:
            if video_id not in seen:
                seen.add(video_id)
                unique_video_ids.append(video_id)

        # If we still don't have enough, try to get more with a different approach
        if len(unique_video_ids) < max_count:
            try:
                main_url = channel_url.replace('/videos?sort=dd', '?sort=dd')
                response = requests.get(main_url, headers=headers)
                response.raise_for_status()

                for pattern in video_id_patterns:
                    matches = re.findall(pattern, response.text)
                    for match in matches:
                        if match not in seen:
                            seen.add(match)
                            unique_video_ids.append(match)
            except:
                pass

        # Limit to requested count
        unique_video_ids = unique_video_ids[:max_count]

        if not unique_video_ids:
            raise ValueError(f"No videos found for username: {username}")

        return unique_video_ids

    except requests.RequestException as e:
        raise RuntimeError(f"Failed to fetch channel page: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to extract video IDs: {e}")


def download_channel_transcripts(username: str, max_count: int, args) -> None:
    """
    Download transcripts from a YouTube channel's latest videos.

    Args:
        username: YouTube username (with or without @)
        max_count: Maximum number of videos to process
        args: Parsed command line arguments

    Raises:
        RuntimeError: If yt-dlp fails or other errors occur
    """
    print(f"Getting video list for {username}...")

    # Get video IDs
    try:
        video_ids = get_channel_video_ids(username, max_count)
        print(f"Found {len(video_ids)} videos")
    except Exception as e:
        raise RuntimeError(f"Failed to get video list: {e}")

    # Create output directory
    clean_username = username.replace('@', '').replace('/', '_').replace('\\', '_')
    output_dir = clean_username

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")

    # Setup proxy configuration
    proxies = None
    if args.proxy:
        proxies = {
            'http': args.proxy,
            'https': args.proxy
        }

    # Process each video
    successful_downloads = 0
    failed_downloads = []

    for i, video_id in enumerate(video_ids, 1):
        print(f"Processing video {i}/{len(video_ids)}: {video_id}")

        try:
            # Get transcript for this video
            transcript = YouTubeTranscriptApi.get_transcript(
                video_id,
                languages=args.languages,
                proxies=proxies,
                cookies=args.cookies,
                preserve_formatting=args.preserve_formatting
            )

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

            # Determine file extension
            file_ext = 'txt'
            if args.format == 'json':
                file_ext = 'json'
            elif args.format == 'srt':
                file_ext = 'srt'
            elif args.format == 'vtt':
                file_ext = 'vtt'

            # Save to file
            filename = f"{i}.{file_ext}"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(formatted_transcript)

            print(f"  Success: Saved {filepath}")
            successful_downloads += 1

        except TranscriptRetrievalError as e:
            print(f"  Failed: No transcript for {video_id}: {e}")
            failed_downloads.append((video_id, str(e)))
        except Exception as e:
            print(f"  Error: Unexpected error for {video_id}: {e}")
            failed_downloads.append((video_id, str(e)))

    # Summary
    print(f"\nDownload completed!")
    print(f"Successfully downloaded: {successful_downloads}")
    print(f"Failed downloads: {len(failed_downloads)}")

    if failed_downloads:
        print("\nFailed videos:")
        for video_id, error in failed_downloads:
            print(f"  {video_id}: {error}")

    print(f"\nTranscripts saved in directory: {output_dir}")


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
  %(prog)s --username @MrBeast --count 50
  %(prog)s --username pewdiepie -n 20 --format json
        """
    )
    
    parser.add_argument(
        'video',
        nargs='?',
        help='YouTube video URL or video ID'
    )

    parser.add_argument(
        '--username', '-u',
        help='YouTube username (with or without @) to download transcripts from their latest videos'
    )

    parser.add_argument(
        '--count', '-n',
        type=int,
        default=10,
        help='Number of latest videos to download transcripts from (default: 10, max: 100)'
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
        # Validate arguments
        if args.username and args.video:
            print("Error: Cannot specify both video and username", file=sys.stderr)
            sys.exit(1)

        if not args.username and not args.video:
            print("Error: Must specify either video or username", file=sys.stderr)
            sys.exit(1)

        # Validate count
        if args.count < 1 or args.count > 100:
            print("Error: Count must be between 1 and 100", file=sys.stderr)
            sys.exit(1)

        # Handle username mode (bulk download)
        if args.username:
            if args.list_transcripts:
                print("Error: --list-transcripts is not supported with --username", file=sys.stderr)
                sys.exit(1)

            print(f"Bulk downloading transcripts for {args.username} (latest {args.count} videos)")
            download_channel_transcripts(args.username, args.count, args)
            return

        # Handle single video mode (original functionality)
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
