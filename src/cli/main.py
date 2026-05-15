from __future__ import annotations

import sys

import requests

from exceptions import TranscriptRetrievalError
from utils.config import apply_config_defaults, load_config
from utils.console import error

from .channel_downloader import download_channel_transcripts
from .helpers import EXIT_API_ERROR, EXIT_NETWORK_ERROR, EXIT_USER_ERROR
from .output import format_and_output
from .parser import create_argument_parser
from .single_video import process_single_video
from .url_parser import is_channel_target


def main() -> None:
    args = create_argument_parser().parse_args()
    apply_config_defaults(args, load_config())

    try:
        if is_channel_target(args.target):
            download_channel_transcripts(args.target, args)
            return

        result = process_single_video(args)
        format_and_output(result, args)

    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(EXIT_USER_ERROR)
    except TranscriptRetrievalError as e:
        error(str(e))
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
