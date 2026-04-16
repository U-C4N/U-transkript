from __future__ import annotations

import argparse
import sys

from __init__ import __version__
from utils.console import error

from .helpers import EXIT_USER_ERROR


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract transcripts from YouTube videos",
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
        """,
    )

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("video", nargs="?", help="YouTube video URL or video ID")
    parser.add_argument(
        "--username",
        "-u",
        help="YouTube username (with or without @) to download transcripts from their latest videos",
    )
    parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=10,
        help="Number of latest videos to download transcripts from (default: 10, max: 100)",
    )
    parser.add_argument(
        "--languages",
        "-l",
        nargs="+",
        help="Language codes in order of preference (e.g., en es fr)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["pretty", "json", "text", "srt", "vtt"],
        default="pretty",
        help="Output format (default: pretty)",
    )
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    parser.add_argument(
        "--list-transcripts",
        action="store_true",
        help="List available transcripts for the video",
    )
    parser.add_argument(
        "--generated-only",
        action="store_true",
        help="Only use auto-generated transcripts",
    )
    parser.add_argument(
        "--manual-only",
        action="store_true",
        help="Only use manually created transcripts",
    )
    parser.add_argument(
        "--preserve-formatting",
        action="store_true",
        help="Preserve HTML formatting in transcript text",
    )
    parser.add_argument("--proxy", help="Proxy URL (e.g., http://proxy:8080)")
    parser.add_argument("--cookies", help="Cookie string for authentication")
    parser.add_argument(
        "--exclude-generated",
        action="store_true",
        help="Exclude auto-generated transcripts",
    )
    parser.add_argument(
        "--exclude-manual",
        action="store_true",
        help="Exclude manually created transcripts",
    )

    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output with detailed progress",
    )
    verbosity.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress all non-essential output",
    )

    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.username and args.video:
        error("Cannot specify both video and username")
        sys.exit(EXIT_USER_ERROR)

    if not args.username and not args.video:
        error("Must specify either video or username")
        sys.exit(EXIT_USER_ERROR)

    if args.count < 1 or args.count > 100:
        error("Count must be between 1 and 100")
        sys.exit(EXIT_USER_ERROR)

    if args.username and args.list_transcripts:
        error("--list-transcripts is not supported with --username")
        sys.exit(EXIT_USER_ERROR)

    if args.generated_only and args.manual_only:
        error("Cannot specify both --generated-only and --manual-only")
        sys.exit(EXIT_USER_ERROR)

    if args.exclude_generated and args.exclude_manual:
        error("Cannot exclude both generated and manual transcripts")
        sys.exit(EXIT_USER_ERROR)
