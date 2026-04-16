from __future__ import annotations

import sys

import requests

from exceptions import TranscriptRetrievalError
from utils.console import error, info, warning
from utils.config import apply_config_defaults, load_config

from .channel_downloader import download_channel_transcripts
from .helpers import (
    EXIT_API_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_USER_ERROR,
)
from .output import format_and_output
from .parser import create_argument_parser, validate_args
from .single_video import process_single_video


def main() -> None:
    parser = create_argument_parser()
    args = parser.parse_args()

    config = load_config()
    apply_config_defaults(args, config)

    try:
        validate_args(args)

        if args.username:
            if not args.quiet:
                info(
                    f"Bulk downloading transcripts for {args.username} "
                    f"(latest {args.count} videos)"
                )
            download_channel_transcripts(args.username, args.count, args)
            return

        result = process_single_video(args)
        format_and_output(result, args)

    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(EXIT_USER_ERROR)
    except TranscriptRetrievalError as e:
        error(str(e))
        if hasattr(e, "suggestion") and getattr(args, "verbose", False):
            warning(f"Suggestion: {e.suggestion}")
        sys.exit(EXIT_API_ERROR)
    except requests.exceptions.RequestException as e:
        error(f"Network error: {e}")
        sys.exit(EXIT_NETWORK_ERROR)
    except ValueError as e:
        error(str(e))
        sys.exit(EXIT_USER_ERROR)
    except Exception as e:
        error(f"Unexpected error: {e}")
        sys.exit(EXIT_USER_ERROR)
