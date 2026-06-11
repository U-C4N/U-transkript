from __future__ import annotations

import argparse

try:
    from __init__ import __version__  # dev checkout: src/ is on sys.path
except ImportError:  # installed wheel: src/__init__.py is not shipped
    from importlib.metadata import version as _dist_version

    __version__ = _dist_version("u-transkript")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="u-transkript",
        description="Extract YouTube transcripts (single video or whole channel).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s dQw4w9WgXcQ
  %(prog)s https://youtu.be/dQw4w9WgXcQ -f srt -o out.srt
  %(prog)s @MrBeast -f json -n 25
  %(prog)s dQw4w9WgXcQ -l en es
  %(prog)s dQw4w9WgXcQ --list-transcripts
  %(prog)s dQw4w9WgXcQ --translate Turkish
""",
    )

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "target",
        help="YouTube video URL / ID, or @username / channel URL for bulk download.",
    )
    parser.add_argument(
        "-l",
        "--languages",
        nargs="+",
        help="Language codes in order of preference (e.g. en es fr).",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["pretty", "json", "text", "srt", "vtt"],
        default="pretty",
        help="Output format (default: pretty).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file for single video, or directory for channel mode.",
    )
    parser.add_argument(
        "-n",
        "--count",
        type=_positive_int,
        default=10,
        help="How many recent videos to download in channel mode (default: 10).",
    )
    parser.add_argument(
        "--list-transcripts",
        action="store_true",
        help="List available transcript languages for the video and exit.",
    )
    parser.add_argument(
        "--translate",
        metavar="LANGUAGE",
        help=(
            "Translate the transcript with Gemini AI to LANGUAGE (e.g. Turkish). "
            "Requires the GEMINI_API_KEY environment variable."
        ),
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the 24-hour transcript disk cache.",
    )

    return parser
