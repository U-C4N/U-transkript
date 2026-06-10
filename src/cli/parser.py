from __future__ import annotations

import argparse

try:
    from __init__ import __version__  # dev checkout: src/ is on sys.path
except ImportError:  # installed wheel: src/__init__.py is not shipped
    from importlib.metadata import version as _dist_version

    __version__ = _dist_version("u-transkript")


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="u-transkript",
        description="Extract YouTube transcripts (single video or whole channel).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s dQw4w9WgXcQ
  %(prog)s https://youtu.be/dQw4w9WgXcQ -f srt -o out.srt
  %(prog)s @MrBeast -f json
  %(prog)s dQw4w9WgXcQ -l en es
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

    return parser
