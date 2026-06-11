from __future__ import annotations

import argparse

from formatters import get_formatter
from youtube_transcript import YouTubeTranscriptApi

from .helpers import build_formatter_kwargs, fetch_transcript_cached
from .url_parser import extract_video_id


def process_single_video(args: argparse.Namespace) -> str:
    video_id = extract_video_id(args.target)
    transcript = fetch_transcript_cached(
        YouTubeTranscriptApi,
        video_id,
        languages=args.languages,
        use_cache=not getattr(args, "no_cache", False),
    )
    formatter = get_formatter(args.format)
    return formatter.format_transcript(transcript, **build_formatter_kwargs(args.format))
