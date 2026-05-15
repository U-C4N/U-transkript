from __future__ import annotations

import argparse

from utils.console import success

_FILE_EXTENSIONS = {
    "json": "json",
    "srt": "srt",
    "vtt": "vtt",
    "pretty": "txt",
    "text": "txt",
}


def file_extension_for(format_name: str) -> str:
    return _FILE_EXTENSIONS.get(format_name, "txt")


def format_and_output(result: str, args: argparse.Namespace) -> None:
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
        success(f"Transcript saved to {args.output}")
    else:
        print(result)
